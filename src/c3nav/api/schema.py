from ninja import Schema


class APIErrorSchema(Schema):
    detail: str
