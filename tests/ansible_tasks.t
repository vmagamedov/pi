Configure:

  $ export LC_ALL=en_US.UTF-8
  $ cat > pi.yaml << EOF
  > - !Image
  >    name: app.env
  >    from: !DockerImage alpine:3.4
  >    repository: app.env
  >    provision-with: !AnsibleTasks
  >      - file: path=/foo.ini state=touch
  > EOF

Setup:

  $ docker rmi app.env:773df759057a > /dev/null 2>&1 || true

Test:

  $ pi image build app.env | tail -n 11
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
