from nicegui.testing import User


async def test_page_renders(user: User) -> None:
    await user.open("/")
    await user.should_see("Weather now")
