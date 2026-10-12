from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ansible_firewall_is_opt_in_and_scoped():
    playbook = (ROOT / "deploy/ansible/mobile-api-firewall.yml").read_text()
    assert "gway_remote_apply_firewall: false" in playbook
    assert "host-security-firewall.service" in playbook
    assert "/etc/nftables.d/host-security.nft" in playbook
    assert 'iifname "gway" ip saddr 10.90.0.1 ip daddr 10.90.0.2 tcp dport 8765 accept' in playbook
    assert "insertbefore:" in playbook
    assert "nft -c -f %s" in playbook
    assert "backup: true" in playbook
    assert "rescue:" in playbook
    assert "ufw allow" not in playbook
    assert "0.0.0.0/0" not in playbook
    assert "ansible.builtin.systemd:" in playbook
    assert "ansible.builtin.service_facts:" not in playbook


def test_terminal_reject_variants_and_apply_after_stage():
    import re

    playbook = (ROOT / "deploy/ansible/mobile-api-firewall.yml").read_text()
    pattern = r'^\\s*(?:counter\\s+)?reject with icmpx(?:\\s+type)? admin-prohibited\\s*$'
    assert re.search(pattern, '        counter reject with icmpx type admin-prohibited', re.M)
    assert re.search(pattern, '        reject with icmpx admin-prohibited', re.M)
    assert 'insertbefore: ' in playbook
    assert 'counter\\\\s+' in playbook
    restart_block = playbook.split('- name: Restart existing host security firewall', 1)[1].split('- name: Verify live rule exists', 1)[0]
    assert 'when: firewall_edit.changed' not in restart_block


def test_lineinfile_patterns_match_actual_host_firewall():
    import re

    playbook = (ROOT / "deploy/ansible/mobile-api-firewall.yml").read_text()
    lines = playbook.splitlines()
    before = next(line.split("'", 2)[1] for line in lines if "insertbefore:" in line)
    existing = next(line.split("'", 2)[1] for line in lines if "regexp:" in line)
    assert re.search(before, '        counter reject with icmpx type admin-prohibited')
    assert re.search(before, '        reject with icmpx admin-prohibited')
    rule = '        iifname "gway" ip saddr 10.90.0.1 ip daddr 10.90.0.2 tcp dport 8765 accept'
    assert re.search(existing, rule)
    assert not re.search(existing, rule.replace("10.90.0.2", "10x90x0x2"))
