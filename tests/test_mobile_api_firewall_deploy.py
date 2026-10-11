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
