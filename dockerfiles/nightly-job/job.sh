#!/usr/bin/env bash

set -e
set -x

env

# Set HOME to /root
export HOME=/root

# Switch to home directory
cd

# We haven't trapped yet
trapped=0

# Cleanup trap
cleanup() {
  # If first trap
  if [[ $trapped -eq 0 ]]
  then
    # We've trapped now
    trapped=1
    # Store exit code
    case $1 in
      INT|TERM|ERR)
        retval=1;; # exit 1 on INT, TERM, ERR
      *)
        retval=$1;; # specified code otherwise
    esac
    # Kill process group, retriggering trap
    kill 0
  fi
  # Disable trap
  trap - INT TERM ERR

  # Rekick the nodes in preperation for the next run.
  [ -e playbooks ] || pushd jenkins-rpc
  [[ $REKICK == "yes" ]] &&  ansible-playbook -i inventory/$LAB -e @vars/$LAB playbooks/rekick-lab.yml ||:

  # Exit
  exit $retval
}

# Set the trap
set_trap cleanup INT TERM ERR

# Clone jenkins-rpc repo
git clone git@github.com:rcbops/jenkins-rpc.git & wait %1
git checkout $targetBranch

if [[ $BUILD == "yes" ]]
then
  # Move into jenkins-rpc
  pushd jenkins-rpc
 
  # Set color and buffer
  export PYTHONUNBUFFERED=1
  export ANSIBLE_FORCE_COLOR=1

  # Preconfigure lab / build RPC / test RPC
  ansible-playbook \
    -i inventory/$LAB \
    -e @vars/$LAB \
    playbooks/nightly-multinode.yml & wait %1
fi

# Exit cleanly
exit 0
