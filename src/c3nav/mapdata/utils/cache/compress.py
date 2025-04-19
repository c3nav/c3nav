import base64
import struct
from collections import deque
from typing import Sequence


bit_len_to_size_type = ((0, ) * 9) + ((1, ) * 8) + ((2, ) * 16) + ((3, ) * 32)
unsigned_sizes = "BHIQ"
signed_sizes = "bhiq"


def get_type_for_size(num_bits) -> int:
    return 0 if num_bits <= 8 else (1 if num_bits <= 16 else 2 if num_bits <= 32 else 3)


def compress_sorted_list_of_int(values: Sequence[int]) -> bytes:
    # todo: compress? speedup, optimize?
    if not values:
        return b""
    value = next(iter_values := iter(values))
    last_value = value
    encoded = deque((value, ))
    span = 0
    try:
        while True:
            # add current value
            span = 0
            # see if next values are just increments of the last one, if so increase span
            while (value := next(iter_values)) == last_value + 1:
                span -= 1
                last_value = value
            # no longer in a span, but was there one?
            if span:
                # if there was one, add the span to the encoded values
                encoded.append(span)
            # then add the new value to the encoded list at the start of the next loop
            encoded.append(value-last_value)
            last_value = value
    except StopIteration:
        pass
    if span:
        encoded.append(span)

    encoded = tuple(encoded)

    # how many bits needed?
    length_type = bit_len_to_size_type[len(encoded).bit_length()]
    first_type = bit_len_to_size_type[encoded[0].bit_length()]
    remainder_type = bit_len_to_size_type[max(i.bit_length() for i in encoded[1:])+1] if len(encoded) > 1 else 0
    return base64.z85encode(struct.pack(
        f"B{unsigned_sizes[length_type]}{unsigned_sizes[first_type]}{signed_sizes[remainder_type]*(len(encoded)-1)}",
        (length_type << 4) + (first_type << 2) + remainder_type,
        len(encoded), *encoded
    ))