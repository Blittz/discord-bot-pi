"""Shared, fail-closed age gate for live downloads and future backfills."""

THREAD_TYPES = {10, 11, 12}
CHANNEL_TYPES = {0, 2, 5, 13, 15, 16}


def _valid_channel(data, channel_id):
    return isinstance(data, dict) and str(data.get('id')) == str(channel_id)


def _flag_reason(data):
    flag = data.get('nsfw')
    if flag is True:
        return 'age-restricted'
    if flag is not False:
        return 'restriction-unknown'
    return None


async def attachment_skip_reason(http, channel_id):
    """Return None only when fresh Discord metadata explicitly permits saving.

    Threads (including forum/media posts) inherit their parent's restriction.
    Never trust Thread.is_nsfw(): it returns False for an uncached parent.
    Do not log exception messages: they may contain credentials or URLs.
    """
    try:
        data = await http.get_channel(channel_id)
        if not _valid_channel(data, channel_id):
            return 'restriction-unknown'
        kind = data.get('type')
        if type(kind) is not int:
            return 'restriction-unknown'
        if kind in THREAD_TYPES:
            # Threads normally omit nsfw and inherit it from the parent.
            if 'nsfw' in data:
                reason = _flag_reason(data)
                if reason:
                    return reason
            parent_id = data.get('parent_id')
            if not isinstance(parent_id, (str, int)) or not str(parent_id).isdigit():
                return 'parent-restriction-unknown'
            parent = await http.get_channel(int(parent_id))
            if (not _valid_channel(parent, parent_id)
                    or parent.get('type') not in {0, 5, 15, 16}):
                return 'parent-restriction-unknown'
            reason = _flag_reason(parent)
            return 'parent-' + reason if reason else None
        if kind not in CHANNEL_TYPES:
            return 'unsupported-channel-restriction-unknown'
        return _flag_reason(data)
    except Exception:
        return 'restriction-metadata-unavailable'
