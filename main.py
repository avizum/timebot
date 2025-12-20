import asqlite
import discord
import toml
from discord.ext import commands


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=self.__class__.get_prefix,
            intents=discord.Intents.default(),
        )

    async def get_prefix(self, message: discord.Message) -> list[str]:
        assert self.user is not None

        if await self.is_owner(message.author):
            return [f"<@{self.user.id}> ", f"<@!{self.user.id}> "]
        return []

    async def create_pool(self):
        await self.wait_until_ready()
        pool = await asqlite.create_pool("data/users.db")
        self.pool = pool

    async def load_extensions(self):
        await self.load_extension("jishaku")
        await self.load_extension("cogs.commands")

    async def setup_hook(self) -> None:
        await self.load_extensions()
        self.loop.create_task(self.create_pool())


bot = Bot()


def main():
    config = toml.load("config.toml")
    bot.run(token=config["token"])


if __name__ == "__main__":
    main()
