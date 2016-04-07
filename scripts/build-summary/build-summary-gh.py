#!/usr/bin/env python

# Stdlib import
import collections
import copy
import datetime
import os
import pickle
import re

# 3rd Party imports
import click
import humanize
import jinja2

# Project imports
from build import Build

# # Jenkins Build Summary Script
# This script reads all the build.xml files specified and prints a summary of
# each job.  This summary includes the cluster it ran on and all the parent
# jobs.  Note that EnvVars.txt is read from the same dir as build.xml.

# Builds older than this will not be cached. This is to prevent the cache
# from growing indefinitely even though jenkins is only retaining 30 days of
# builds. This value should be the same as the jenkins retain days value.
RETENTION_DAYS = 30


class TSF(object):
    """Total, Success, Failure """
    def __init__(self, t=0, s=0):
        self.t = int(t)
        self.s = int(s)

    @property
    def f(self):
        return self.t - self.s

    @property
    def s_percent(self):
        try:
            return (float(self.s)/float(self.t))*100.0
        except ZeroDivisionError:
            return 0

    def success(self):
        self.t += 1
        self.s += 1

    def failure(self):
        self.t += 1

    def b(self, build):
        if build.result == "SUCCESS":
            self.success()
        else:
            self.failure()


def print_html(buildobjs):
    buildobjs = buildobjs.values()
    failcount = collections.defaultdict(dict)

    # remove 'task failed' if 'too many retries' also exists for same task
    task_failed_re = re.compile('Task Failed: (?P<task>.*)')
    for build in buildobjs:
        for failure in copy.copy(build.failures):
            match = task_failed_re.search(failure)
            if match and 'Too many retries. PrevTask: {task}'.format(
                    task=match.groupdict()['task']) in build.failures:
                build.failures.remove(failure)

    for build in buildobjs:
        for failure in build.failures:
            d = failcount[failure]
            if 'count' not in d:
                d['count'] = 0
            d['count'] += 1
            if 'builds' not in d:
                d['builds'] = []
            d['builds'].append(build)
            if 'oldest' not in d or d['oldest'] > build.timestamp:
                d['oldest'] = build.timestamp
                d['oldest_job'] = build.build_num
                d['oldest_bobj'] = build
            if 'newest' not in d or d['newest'] < build.timestamp:
                d['newest'] = build.timestamp
                d['newest_job'] = build.build_num
                d['newest_bobj'] = build

    # Organise the builds for each failure into 24hr bins for sparklines
    histogram_length = RETENTION_DAYS
    now = datetime.datetime.now()
    for failure, fdict in failcount.items():
        fdict['histogram'] = [0] * histogram_length
        for build in fdict['builds']:
            age_days = (now - build.timestamp).days
            if age_days <= histogram_length:
                fdict['histogram'][histogram_length - age_days - 1] += 1

    if 'Unknown Failure' in failcount:
        del failcount['Unknown Failure']

    buildcount = collections.defaultdict(TSF)
    twodaysago = datetime.datetime.now() - datetime.timedelta(days=2)
    for build in [b for b in buildobjs if b.timestamp > twodaysago]:
        buildcount['all'].b(build)
        buildcount[build.branch].b(build)
        buildcount[build.trigger].b(build)
        buildcount[build.btype].b(build)
        buildcount['{b}_{s}_{t}'.format(
                   b=build.branch,
                   s=build.btype,
                   t=build.trigger)].b(build)

    def dt_filter(date):
        """Date time filter

        Returns a human readable string for a datetime object.
        """
        return '{time} {date}'.format(
            time=date.strftime('%H:%M'),
            date=humanize.naturalday(date)
        )

    jenv = jinja2.Environment()
    jenv.filters['hdate'] = dt_filter
    template = jenv.from_string(open("buildsummary.j2", "r").read())
    print(template.render(
        buildcount=buildcount,
        buildobjs=buildobjs,
        timestamp=datetime.datetime.now(),
        failcount=failcount))


@click.command(help='args are paths to jenkins build.xml files')
@click.argument('builds', nargs=-1)
@click.option('--newerthan', default=0,
              help='Build IDs older than this will not be shown')
@click.option('--cache', default='/opt/jenkins/www/.cache')
def summary(builds, newerthan, cache):

    if os.path.exists(cache):
        with open(cache, 'rb') as f:
            buildobjs = pickle.load(f)
    else:
        buildobjs = {}

    for build in builds:
        path_groups_match = re.search(
            ('^(?P<build_folder>.*/(?P<job_name>[^/]+)/'
             'builds/(?P<build_num>[0-9]+))/'), build)
        if path_groups_match:
            path_groups = path_groups_match.groupdict()
            if path_groups['build_num'] in buildobjs:
                continue
            buildobjs[path_groups['build_num']] = Build(
                build_folder=path_groups['build_folder'],
                job_name=path_groups['job_name'],
                build_num=path_groups['build_num'])

    print_html(buildobjs)

    # Pickle build objs newer than RETENTION_DAYS to the cache file, so those
    # logs don't need to be reprocessed on the next run.
    age_limit = (datetime.datetime.now()
                 - datetime.timedelta(days=RETENTION_DAYS))
    cache_dict = {}
    for num, build in buildobjs.items():
        if build.timestamp > age_limit:
            cache_dict[num] = build
    with open(cache, 'wb') as f:
        pickle.dump(cache_dict, f, pickle.HIGHEST_PROTOCOL)

if __name__ == '__main__':
    summary()
