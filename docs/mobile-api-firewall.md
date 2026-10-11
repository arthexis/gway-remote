# GWay-001: persistent mobile API firewall exception

The existing `host-security-firewall.service` owns the `inet host_security` table and reloads `/etc/nftables.d/host-security.nft`. Do not create a new service, nftables table, UFW rule, or public TCP listener.

The temporary runtime exception must be made persistent:

```nft
iifname "gway" ip saddr 10.90.0.1 ip daddr 10.90.0.2 tcp dport 8765 accept
```

The playbook checks for the expected table, input chain and a unique terminal reject, inserts the rule before the reject, validates the resulting file using `nft -c -f`, and backs up the original. By default it **only stages the persistent file**; the existing runtime rule continues to work.

Run from a control machine with Ansible installed and SSH/sudo access to GWay-001:

```sh
ansible-playbook -i 'gway-001,' -u arthe --become deploy/ansible/mobile-api-firewall.yml
```

Review the staged rule and verify the host has a recovery route before activating:

```sh
ssh arthe@gway-001 'sudo nft -c -f /etc/nftables.d/host-security.nft'
ansible-playbook -i 'gway-001,' -u arthe --become deploy/ansible/mobile-api-firewall.yml -e gway_remote_apply_firewall=true
```

The explicit apply restarts the **existing** host-security service and checks the live input chain. If apply fails, Ansible attempts to restore the original file and restart the service. Network disruption can sever the Ansible connection before rescue runs; have console/local access or an independent rollback mechanism before applying remotely. A staged-only run does not guarantee the rule is active until the next firewall restart.

Finally verify `sudo nft list chain inet host_security input` and an authenticated `https://remote.arthexis.com/api/v1/health` request. To test persistence, restart the existing firewall service (not the whole host) during a maintenance window and retest. Do not paste the bearer token into logs.
