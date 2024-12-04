# User model schema
class User:
    def __init__(self, name, age, points, address):
        self.name = name
        self.age = age
        self.points = points
        self.address = address

    def to_dict(self):
        return {
            "name": self.name,
            "age": self.age,
            "points": self.points,
            "address": self.address
        }