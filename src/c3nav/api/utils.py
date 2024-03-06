from typing import Annotated

import annotated_types

NonEmptyStr = Annotated[str, annotated_types.MinLen(1)]
