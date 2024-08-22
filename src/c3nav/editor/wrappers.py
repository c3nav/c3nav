def is_created_pk(pk):
    return isinstance(pk, str) and pk.startswith('c') and pk[1:].isnumeric()

