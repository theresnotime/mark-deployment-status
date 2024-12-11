import mark_deployment_status


def test_update_deployment_status(mocker):
    title = "Add Atieno's public key"
    gerrit_id = "1101577"
    sal_content = """
    <tr>
        <td class="time"><a href="/log/2UkrtpMBKFqumxvtMweK">14:41</a></td>
        <td class="nick">&lt;samtar@deploy2002&gt;</td>
        <td class="message">Finished scap sync-world: Backport for [[<a href="https://gerrit.wikimedia.org/r/#/c/1101577" target="_blank">gerrit:1101577</a>|Add Atieno's public key]] (duration: 08m 47s)</td>
        <td class="project">[production]</td>
    </tr>"""
    in_log = mark_deployment_status.get_sal_entry_regex(title, gerrit_id).search(
        sal_content
    )
    mocker.patch("mark_deployment_status.did_change_get_deployed", return_value=in_log)
    deployment_string_pre = (
        "{{deploy|type=config|gerrit=1101577|title=Add Atieno's public key|status=}}"
    )
    deployment_string_post = "{{deploy|type=config|gerrit=1101577|title=Add Atieno's public key|status=done|by=samtar|sal=https://sal.toolforge.org/log/2UkrtpMBKFqumxvtMweK}}"
    assert (
        mark_deployment_status.update_deployment_status(
            "", deployment_string_pre, "MERGED", ""
        )
        == deployment_string_post
    )
