# Skeleton test — verifies the package is importable.
# Replaced by real tests starting from task S-2.


def test_package_importable() -> None:
    import toolfence  # noqa: F401
    import toolfence.contracts  # noqa: F401
    import toolfence.engine  # noqa: F401
    import toolfence.guard  # noqa: F401
    import toolfence.integration  # noqa: F401
    import toolfence.cli  # noqa: F401
    import toolfence.bob  # noqa: F401
