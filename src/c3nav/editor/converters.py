class EditPkConverter:
    regex = r'c?\d+'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value
