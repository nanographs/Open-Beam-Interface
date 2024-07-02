class Context:
    def __enter__(self):
        print("Entering")
        return self
    def __exit__(self, *args, **kwargs):
        print(f"{test=}")
        print("Exiting")

with Context() as context:
    print("Hello")
    test = "Test"