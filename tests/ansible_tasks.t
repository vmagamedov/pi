Configure:

  $ export LC_ALL=en_US.UTF-8
  $ cat > pi.yaml << EOF
  > - !Image
  >    name: app.env
  >    from: !DockerImage ubuntu:xenial
  >    repository: app.env
  >    provision-with: !AnsibleTasks
  >      - file: path=/foo.ini state=touch
  > EOF

Setup:

  $ docker rmi app.env:773df759057a > /dev/null 2>&1 || true

Test:

  $ pi image build app.env
  Pulling repository docker.io/library/app.env
  Error: image library/app.env:773df759057a not found
   (esc)
  PLAY [*] * (glob)
   (esc)
  TASK [setup] *******************************************************************
  ok: [*] (glob)
   (esc)
  TASK [file] ********************************************************************
  changed: [*] (glob)
   (esc)
  PLAY RECAP *********************************************************************
  * : ok=2 * changed=1 * unreachable=0 * failed=0 * (glob)
   (esc)
