#!/usr/bin/env bash
LAB=${LAB:-master}
ANSIBLE_OPTIONS=${ANSIBLE_OPTIONS:--v}

ansible-playbook \
  -i inventory/nighty-${LAB} \
  -e @vars/nightly-${LAB}.yml \
  $ANSIBLE_OPTIONS \
  nightly-rekick.yml
  
