import json


def _preencode(data, magic_marker):
    if isinstance(data, dict):
        data = data.copy()
        for name, value in tuple(data.items()):
            if name in ('bounds', ):
                data[name] = magic_marker+json.dumps(value)+magic_marker
            else:
                data[name] = _preencode(value, magic_marker)
        return data
    elif isinstance(data, (tuple, list)):
        return tuple(_preencode(value, magic_marker) for value in data)
    else:
        return data


def json_encoder_reindent(method, data, *args, **kwargs):
    magic_marker = '***JSON_MAGIC_MARKER***'
    test_encode = json.dumps(data)
    while magic_marker in test_encode:
        magic_marker += '*'
    result = method(_preencode(data, magic_marker), *args, **kwargs)
    if type(result) == str:
        return result.replace('"'+magic_marker, '').replace(magic_marker+'"', '')
    else:
        magic_marker = magic_marker.encode()
        return result.replace(b'"'+magic_marker, b'').replace(magic_marker+b'"', b'')
