# Stdlib import
import datetime
import re

# 3rd Party imports
# Imports with C deps
# remember to install all the apt xml stuff - not just the pip packages.
from lxml import etree


class Build(object):
    """Build Object

    Represents one RPC-AIO build. Contains functionality for intepreting
    the build.xml, injected_vars and log files.
    """
    def __init__(self, build_folder, job_name, build_num):
        self.tree = etree.parse('{bf}/build.xml'.format(
            bf=build_folder,
            job_name=job_name,
            build_num=build_num))
        self.result = self.tree.find('./result').text
        # jenkins uses miliseconds not seconds
        self.timestamp = datetime.datetime.fromtimestamp(
            float(self.tree.find('startTime').text)/1000)
        self.build_folder = build_folder
        self.job_name = job_name
        self.build_num = build_num
        self.env_file = '{build_folder}/injectedEnvVars.txt'.format(
            build_folder=self.build_folder)
        self.env_vars = self.read_env_file(self.env_file)
        self.branch = self.env_vars['ghprbTargetBranch']
        self.commit = self.env_vars.get('ghprbActualCommit', '')
        if self.env_vars['DEPLOY_CEPH'] == 'yes':
            self.btype = 'ceph'
        else:
            self.btype = 'full'
        self.get_parent_info()
        self.failures = []
        if self.result != 'SUCCESS':
            self.get_failure_info()

    def read_env_file(self, path):
        kvs = {}
        with open(path) as env_file:
            for line in env_file:
                line = line.split('=')
                if len(line) < 2:
                    continue
                kvs[line[0].strip()] = line[1].strip()
        return kvs

    def get_parent_info(self):
        self.upstream_project = self.tree.find('.//upstreamProject').text
        self.upstream_build_no = self.tree.find('.//upstreamBuild').text
        prinfo = self.tree.find('.//org.jenkinsci.plugins.ghprb.GhprbCause')
        self.trigger = "periodic"
        if prinfo is not None:
            # build started by pr
            self.trigger = "pr"
            self.gh_pull = self.tree.find('.//pullID').text
            self.gh_target = self.tree.find('.//targetBranch').text
            self.gh_title = self.tree.find(
                './/org.jenkinsci.plugins.ghprb.GhprbCause/title').text

    def get_failure_info(self):
        self.console_file = '{build_folder}/log'.format(
            build_folder=self.build_folder)
        lines = open(self.console_file, 'r').readlines()
        try:
            post_build = lines.index(
                '[PostBuildScript] - Execution post build scripts.\n')
            lines = lines[0: post_build]
        except Exception:
            pass

        if self.result == 'ABORTED':
            self.timeout(lines)
        if self.result == 'FAILURE':
            self.glance_504(lines)
            self.apt_mirror_fail(lines)
            self.too_many_retries(lines)
            self.ssh_fail(lines)
            self.service_unavailable(lines)
            self.rebase_fail(lines)
            self.rsync_fail(lines)
            self.elasticsearch_plugin_install(lines)
            self.tempestfail(lines)
            self.portnotfound(lines)
            self.secgroup_in_use(lines)
            self.cannot_find_role(lines)
            self.ceilometer_user_not_found(lines)
            self.dpkg_locked(lines)
            self.maas_alarm(lines)
            self.setup_tools_sql_alchemy(lines)
            self.ansible_task_fail(lines)
            # if not self.failures:
            #    self.deploy_rc(lines)

        if not self.failures:
            self.failures.append("Unknown Failure")

    def ansible_task_fail(self, lines):
        match_re = re.compile('failed:.*=>.*failed')
        for i, line in enumerate(lines):
            match = match_re.search(line)
            if match:
                previous_task = self.get_previous_task(i, lines)
                if not self.failure_ignored(i, lines):
                    self.failures.append('Task Failed: {task}'.format(
                        task=previous_task))

    def setup_tools_sql_alchemy(self, lines):
        match_str = ("error in SQLAlchemy-Utils setup command: "
                     "'extras_require' must be a dictionary")
        for i, line in enumerate(lines):
            if match_str in line:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "Setup Tools / SQL Alchemy Fail. PrevTask: {task}".format(
                        task=previous_task))
                break

    def maas_alarm(self, lines):
        match_str = 'Checks and Alarms with failures:'
        for i, line in enumerate(lines):
            if match_str in line:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "Maas Alarm in alert state. PrevTask: {task}".format(
                        task=previous_task))
                break

    def dpkg_locked(self, lines):
        match_str = 'dpkg status database is locked by another process'
        alt_match_str = 'Could not get lock /var/lib/dpkg/lock'
        for i, line in enumerate(lines):
            if match_str in line or alt_match_str in line:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "dpkg locked. PrevTask: {task}".format(
                        task=previous_task))
                break

    def ceilometer_user_not_found(self, lines):
        match_str = 'user [ ceilometer ] was not found'
        for i, line in enumerate(lines):
            if match_str in line:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "user ceilometer not found. PrevTask: {task}".format(
                        task=previous_task))
                break

    def cannot_find_role(self, lines):
        match_str = 'cannot find role in'
        for i, line in enumerate(lines):
            if match_str in line:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "Cannot find role. PrevTask: {task}".format(
                        task=previous_task))
                break

    def secgroup_in_use(self, lines):
        match_re = re.compile('Security Group [^ ]* in use')
        for i, line in enumerate(lines):
            match = match_re.search(line)
            if match:
                self.failures.append('Nova/Neutron Error: '
                                     'Security Group ... in use')
                break

    def portnotfound(self, lines):
        match_re = re.compile('neutronclient.common.exceptions.'
                              'PortNotFoundClient')
        for i, line in enumerate(lines):
            match = match_re.search(line)
            if match:
                self.failures.append('Nova/Neutron Exception: '
                                     'neutronclient.common.exceptions'
                                     '.PortNotFoundClient')
                break

    def tempestfail(self, lines):
        match_re = re.compile('\{0\}.*(?P<test>tempest[^ ]*).*\.\.\. FAILED')
        for i, line in enumerate(lines):
            match = match_re.search(line)
            if match:
                test = match.groupdict()['test']
                self.failures.append('Tempest Test Failed: {test}'.format(
                    test=test))

    def elasticsearch_plugin_install(self, lines):
        match_str = 'failed to download out of all possible locations...'
        for i, line in enumerate(lines):
            if match_str in line:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "Elasticsearch Plugin Install Fail. "
                    "PrevTask: {task}".format(
                        task=previous_task))
                break

    def deploy_rc(self, lines):
        match_re = re.compile("DEPLOY_RC=[123456789]")
        remove_colour = re.compile('ha:[^ ]+AAA=+')
        for i, line in enumerate(lines):
            if match_re.search(line):
                beforecontext = lines[i-1:i-4:-1]
                for j, cline in enumerate(beforecontext):
                    beforecontext[j] = remove_colour.sub('', cline)
                self.failures.append("Unkown:" + " ".join(beforecontext))
                break

    def rsync_fail(self, lines):
        match_re = re.compile('failed:.*rsync -avzlHAX')
        for i, line in enumerate(lines):
            if match_re.search(line):
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    'Failure Running Rsync. PrevTask: {task}'.format(
                        task=previous_task))
                break

    def ssh_fail(self, lines):
        match_str = ("SSH Error: data could not be sent to the remote host. "
                     "Make sure this host can be reached over ssh")
        for line in lines:
            if match_str in line:
                self.failures.append(match_str.strip())
                break

    def rebase_fail(self, lines):
        match_str = "Rebase failed, quitting\n"
        try:
            lines.index(match_str)
            self.failures.append("Merge Conflict: " + match_str.strip())
        except ValueError:
            return

    def too_many_retries(self, lines):
        match_str = 'msg: Task failed as maximum retries was encountered'
        for i, line in enumerate(lines):
            if match_str in line and '...ignoring' not in lines[i+1]:
                previous_task = self.get_previous_task(i, lines)
                self.failures.append(
                    "Too many retries. PrevTask: {task}".format(
                        task=previous_task))
                break

    def get_previous_task(self, line, lines, order=-1, get_line_num=False):
        previous_task_re = re.compile(
            'TASK: \[((?P<role>.*)\|)?(?P<task>.*)\]')
        if order == -1:
            end = 0
        else:
            end = len(lines)
        for index in range(line, end, order):
            match = previous_task_re.search(lines[index])
            if match:
                gd = match.groupdict()
                if get_line_num:
                    return index
                else:
                    if 'role' in gd:
                        return '{role}/{task}'.format(
                            role=gd['role'], task=gd['task'])
                    else:
                        return gd['task']

        return ""

    def failure_ignored(self, fail_line, lines):
        next_task_line = self.get_previous_task(fail_line,
                                                lines,
                                                order=1,
                                                get_line_num=True)
        if next_task_line == "":
            return False

        for line in lines[fail_line:next_task_line]:
            if '...ignoring' in line:
                return True
        return False

    def service_unavailable(self, lines):
        match_str = ('ERROR: Service Unavailable (HTTP 503)')
        for i, line in enumerate(lines):
            if match_str in line:
                fail_line = i
                break
        else:
            # didn't find a match
            return
        previous_task = self.get_previous_task(fail_line, lines)
        self.failures.append(
            'Service Unavailable 503. PrevTask: {previous_task}'.format(
                previous_task=previous_task))

    def timeout(self, lines):
        match_str = ('Build timed out (after 20 minutes). '
                     'Marking the build as aborted.\n')
        try:
            timeout_line = lines.index(match_str)
        except ValueError:
            return
        previous_task = self.get_previous_task(timeout_line, lines)
        self.failures.append(
            'Inactivity Timeout: {previous_task}'.format(
                previous_task=previous_task))

    def apt_mirror_fail(self, lines):
        match_str = ("WARNING: The following packages cannot be "
                     "authenticated!\n")
        try:
            i = lines.index(match_str)
            previous_task = self.get_previous_task(i, lines)
            self.failures.append("Apt Mirror Fail: {line} {task}".format(
                line=match_str.strip(),
                task=previous_task))
        except ValueError:
            return

    def glance_504(self, lines):
        match_str = ("glanceclient.exc.HTTPException: 504 Gateway Time-out: "
                     "The server didn't respond in time. (HTTP N/A)\n")
        try:
            lines.index(match_str)
            self.failures.append("Cirros upload fail: " + match_str.strip())
        except ValueError:
            return

    def __str__(self):
        s = ("{timestamp} {result} {job_name}/{build_num} --> "
             "{upstream_project}/{upstream_build_no}").format(
            timestamp=self.timestamp.isoformat(),
            job_name=self.job_name,
            build_num=self.build_num,
            result=self.result,
            upstream_project=self.upstream_project,
            upstream_build_no=self.upstream_build_no)
        if hasattr(self, 'gh_pull'):
            s += ' pr/{gh_pull} target:{gh_target} "{gh_title}"'.format(
                gh_pull=self.gh_pull,
                gh_target=self.gh_target,
                gh_title=self.gh_title)
        if self.failures:
            s += " " + ",".join(self.failures)
        return s
