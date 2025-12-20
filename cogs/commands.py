from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from typing import Mapping, TYPE_CHECKING, TypedDict

import discord
from discord import app_commands, ui
from discord.ext import commands

if TYPE_CHECKING:
    from main import Bot


class ZoneData(TypedDict):
    id: int
    user_id: int
    time_zone: str | None
    utc_offset: str | None
    time_format: str
    default_zone: bool


FORMAT_MAP: Mapping[str, str] = {
    "%-I:%M %p": "12 hour",
    "%-I:%M:%S %p": "12 hour with seconds",
    "%H:%M": "24 hour",
    "%H:%M:%S": "24 hour with seconds",
}


class TimeZoneModal(ui.Modal, title="Time Zone Information"):
    time_zone = ui.Label(
        text="Time Zone",
        description="Enter a time zone name.",
        component=ui.TextInput(placeholder="America/New_York", required=False),
    )

    note = ui.TextDisplay(
        "For daylight saving time support, fill in **only** the Time Zone field with a time zone found "
        "[here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List) above.\n"
        "Otherwise, fill in **only** the UTC Offset field below."
    )

    utc_offset = ui.Label(
        text="UTC Offset",
        description="Must be in the format of ±HH:MM. This is ignored if Time Zone is filled in.",
        component=ui.TextInput(
            min_length=6, max_length=6, placeholder="-05:00", required=False
        ),
    )

    time_format = ui.Label(
        text="Time Format",
        description="Choose a format you prefer.",
        component=ui.Select(
            options=[
                discord.SelectOption(
                    label="12 hour",
                    value="%-I:%M %p",
                    description="11:24 PM",
                ),
                discord.SelectOption(
                    label="12 hour with seconds",
                    value="%-I:%M:%S %p",
                    description="11:24:05 PM",
                ),
                discord.SelectOption(
                    label="24 hour",
                    value="%H:%M",
                    description="23:24",
                ),
                discord.SelectOption(
                    label="24 hour with seconds",
                    value="%H:%M:%S",
                    description="23:24:05",
                ),
            ]
        ),
    )

    default_zone = ui.Label(
        text="Set as default zone?",
        description="This will be used for comparison with other time zones.",
        component=ui.Select(
            options=[
                discord.SelectOption(label="Yes", value="1"),
                discord.SelectOption(label="No", value="0"),
            ],
        ),
    )

    def __init__(
        self, /, *, bot: Bot, data: ZoneData | None = None, view: SettingsView
    ) -> None:
        self.bot = bot
        self.data = data
        self.view = view
        super().__init__(timeout=None)
        self.set_defaults()

    def set_defaults(self) -> None:
        default_exists: bool = any(
            zone["default_zone"] for zone in self.view.data.values()
        )

        assert isinstance(self.default_zone.component, ui.Select)
        assert self.default_zone.description is not None

        if default_exists:
            self.default_zone.component.options[1].default = True
        else:
            self.default_zone.component.options[0].default = True

        if not self.data:
            return

        assert isinstance(self.time_zone.component, ui.TextInput)
        assert isinstance(self.utc_offset.component, ui.TextInput)
        assert isinstance(self.time_format.component, ui.Select)

        if self.data["default_zone"] is not None:
            options = self.default_zone.component.options
            options[0].default = False
            options[1].default = False

            if self.data["default_zone"] == 1:
                options[0].default = True
            if self.data["default_zone"] == 0:
                options[1].default = True

        options = self.time_format.component.options
        for option in options:
            if self.data["time_format"] == option.value:
                option.default = True
                break

        if self.data["time_zone"]:
            self.time_zone.component.default = self.data["time_zone"]

        if self.data["utc_offset"]:
            self.utc_offset.component.default = self.data["utc_offset"]

    async def on_submit(self, itn: discord.Interaction[Bot]):
        assert isinstance(self.time_zone.component, ui.TextInput)
        assert isinstance(self.utc_offset.component, ui.TextInput)
        assert isinstance(self.time_format.component, ui.Select)
        assert isinstance(self.default_zone.component, ui.Select)

        time_zone = self.time_zone.component.value or None
        utc_offset = self.utc_offset.component.value or None
        time_format = self.time_format.component.values[0]
        default_zone = bool(int(self.default_zone.component.values[0]))

        if not time_zone and not utc_offset:
            return await itn.response.send_message(
                "The Time Zone field and the UTC offset cannot be left blank.",
                ephemeral=True,
            )

        if time_zone and utc_offset:
            utc_offset = None

        if time_zone:
            try:
                time_zone = str(zoneinfo.ZoneInfo(time_zone))
            except zoneinfo.ZoneInfoNotFoundError:
                return await itn.response.send_message(
                    "The time zone you entered is invalid.\n"
                    "Check your capitalization, spelling, or see all the valid time zones [here.](<https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List>)",
                    ephemeral=True,
                )

        if utc_offset:
            split = utc_offset.split(":")
            hours = abs(int(split[0]))
            minutes = int(split[1])
            if hours > 24 or (hours == 24 and minutes):
                return await itn.response.send_message(
                    "A UTC offset cannot have more than a 24 hour difference.\n"
                    "Please enter an offset less than 24 hours.",
                    ephemeral=True,
                )

            if int(minutes) > 59:
                return await itn.response.send_message(
                    "The UTC offset format is ±HH:MM. The number of minutes you entered exceeded 59.",
                    ephemeral=True,
                )

        async with self.bot.pool.acquire() as conn:
            if default_zone:
                for zone in self.view.data.values():
                    if zone["default_zone"]:
                        zone["default_zone"] = False
                        default_id = zone["id"]
                        await conn.execute(
                            "UPDATE time_zones SET default_zone = ? where id = ?",
                            (False, default_id),
                        )
                        break
            if not self.data:
                data: ZoneData = await conn.fetchone(
                    """
                    INSERT INTO time_zones (user_id, time_zone, utc_offset, time_format, default_zone)
                    VALUES (?, ?, ?, ?, ?)
                    RETURNING *
                    """,
                    (itn.user.id, time_zone, utc_offset, time_format, default_zone),
                )  # type: ignore
                self.view.data[data["id"]] = ZoneData(data)
            else:
                data: ZoneData = await conn.fetchone(
                    """
                    UPDATE time_zones
                    SET time_zone = ?, utc_offset = ?, time_format = ?, default_zone = ?
                    WHERE id = ?
                    RETURNING *
                    """,
                    (time_zone, utc_offset, time_format, default_zone, self.data["id"]),
                )  # type: ignore
                self.view.data[data["id"]] = ZoneData(data)

        return await itn.response.send_message(
            f"Added {time_zone or utc_offset} to your time zones.", ephemeral=True
        )


class TimeZoneRemovalModal(ui.Modal, title="Remove a Time Zone"):
    select_label = ui.Label(
        text="Time Zone",
        description="Choose the time zones you would like to remove.",
        component=ui.Select(),
    )

    def __init__(self, /, *, view: SettingsView, zones: dict[int, ZoneData]) -> None:
        self.view = view
        self.zones = zones
        self.selected: list[str] = []
        self.interaction: discord.Interaction[Bot] | None = None
        super().__init__()

        select = self.select_label.component
        assert isinstance(select, ui.Select)
        self.select = select

        select.max_values = len(zones)

        for zone in zones.values():
            label = (
                zone["utc_offset"]
                if zone["utc_offset"]
                else zone["time_zone"] or "Unknown"
            )
            select.add_option(label=label, value=f"{label}::{zone["id"]}")

    async def on_submit(self, itn: discord.Interaction[Bot]) -> None:
        removed = []
        async with self.view.bot.pool.acquire() as conn:
            for zone in self.select.values:
                splitted = zone.split("::")
                zone_id = int(splitted[1])
                await conn.execute("DELETE FROM time_zones WHERE id = ?", zone_id)
                self.view.data.pop(zone_id, None)
                removed.append(splitted[0])

        await itn.response.send_message(
            f"The following time zones were removed:\n{", ".join(removed)}",
            ephemeral=True,
        )


class TimeZoneModalButton(ui.Button["SettingsView"]):
    def __init__(self, /, *, data: ZoneData | None) -> None:
        self.data: ZoneData | None = data
        super().__init__(
            style=discord.ButtonStyle.primary if data else discord.ButtonStyle.success,
            label="Edit" if data else "Add add a time zone...",
        )

    async def callback(self, itn: discord.Interaction[Bot]):
        assert self.view is not None
        if len(self.view.data) >= 10:
            return await itn.response.send_message(
                "You cannot have more than 10 time zones saved. Remove some first.",
                ephemeral=True,
            )
        modal = TimeZoneModal(bot=self.view.bot, data=self.data, view=self.view)
        await itn.response.send_modal(modal)
        await modal.wait()
        self.view.container._update()
        return await itn.edit_original_response(view=self.view)


class TimeZoneAction(ui.ActionRow["SettingsView"]):
    def __init__(self) -> None:
        super().__init__()
        self.clear_items()
        self.add_zone = TimeZoneModalButton(data=None)
        self.add_item(self.add_zone)
        self.add_item(self.remove_zone)

    @ui.button(label="Remove time zones...", style=discord.ButtonStyle.danger)
    async def remove_zone(self, itn: discord.Interaction[Bot], button: ui.Button):
        assert self.view is not None

        if not self.view.data:
            await itn.response.defer()

        modal = TimeZoneRemovalModal(view=self.view, zones=self.view.data)

        await itn.response.send_modal(modal)
        await modal.wait()

        self.view.container._update()
        await itn.edit_original_response(view=self.view)


class SettingsView(ui.LayoutView):
    def __init__(self, /, *, bot: Bot, zones: list[ZoneData]) -> None:
        self.bot: Bot = bot
        self.data: dict[int, ZoneData] = {}

        for zone in zones:
            self.data[zone["id"]] = ZoneData(zone)

        super().__init__()
        self.container = SettingsContainer()
        self.add_item(self.container)
        self.container._update()


class SettingsContainer(ui.Container["SettingsView"]):
    title = ui.TextDisplay("### Settings")

    def __init__(self) -> None:
        super().__init__()
        self.action = TimeZoneAction()

    def _update(self) -> None:
        assert self.view is not None

        self.clear_items()

        self.add_item(self.title)
        self.action.remove_zone.disabled = False
        self.action.add_zone.disabled = False

        if not self.view.data:
            self.add_item(ui.TextDisplay("You have no time zones added."))
            self.action.remove_zone.disabled = True

        if len(self.view.data) > 10:
            self.action.add_zone.disabled = True

        for zone in self.view.data.values():
            current = zone["default_zone"]
            offset = zone["utc_offset"]
            time_zone = zone["time_zone"]
            time_format = FORMAT_MAP[zone["time_format"]]
            title = f"UTC Offset: {offset}" if offset else f"Time Zone: {time_zone}"

            self.add_item(
                ui.Section(
                    f"**{title}**\n"
                    f"> Time Format: {time_format}\n"
                    f"> Default Zone: {"Yes" if current else "No"}",
                    accessory=TimeZoneModalButton(data=zone),
                )
            )

        self.add_item(self.action)


class TimeContainer(ui.Container):
    def __init__(
        self,
        /,
        *,
        data: list[ZoneData],
        user: discord.User | discord.Member | None = None,
    ) -> None:

        opted, default_zone, default_format = self.parse_time_zones(data)
        default_time_now = dt.datetime.now(default_zone)
        formatted_times = self.format_times(opted, default_time_now)
        time_info = self.create_time_info(
            default_time_now, default_format, user, default_zone
        )

        if not formatted_times:
            formatted_times.append(
                f"{f"{user.mention} is" if user else "You are"} not following any other time zones."
            )

        super().__init__(
            ui.TextDisplay(f"### Time Information\n{time_info}"),
            ui.TextDisplay("\n".join(formatted_times)),
        )

    def parse_time_zones(
        self, data: list[ZoneData]
    ) -> tuple[list[tuple[dt.timezone, str]], dt.timezone | None, str | None]:

        opted: list[tuple[dt.timezone, str]] = []
        default_zone: dt.timezone | None = None
        default_format: str | None = None

        for zone in data:
            time_zone = zone["time_zone"]
            utc_offset = zone["utc_offset"]

            if time_zone:
                time_zone = zoneinfo.ZoneInfo(time_zone)
                offset = dt.datetime.now(time_zone).utcoffset()
                assert offset is not None

                total_minutes = int(offset.total_seconds() // 60)
                hours, minutes = divmod(total_minutes, 60)
                sign = "+" if total_minutes >= 0 else ""
                name = f"UTC{sign}{hours:02d}:{minutes:02d}"

            elif utc_offset:
                offset = utc_offset.split(":")
                hours = int(offset[0])
                minutes = int(offset[1])
                name = f"UTC{utc_offset}"

            else:
                continue

            name = re.sub(r"UTC([+-])0?(\d+)(?::00)?", r"UTC\1\2", name)
            is_default_zone = bool(zone["default_zone"])

            delta_offset = dt.timedelta(hours=hours, minutes=minutes)

            if is_default_zone:
                default_zone = dt.timezone(delta_offset, name=name)
                default_format = zone["time_format"]
            else:
                opted.append(
                    (dt.timezone(delta_offset, name=name), zone["time_format"])
                )

        return opted, default_zone, default_format

    def format_times(
        self, opted: list[tuple[dt.timezone, str]], default_time_now: dt.datetime
    ) -> list[str]:
        formatted_times: list[str] = []

        for zone, time_format in opted:
            offset_time_now = dt.datetime.now(zone)
            day = offset_time_now.day - default_time_now.day

            formatted_times.append(
                f"[{offset_time_now.tzname()}] {offset_time_now.strftime(time_format)}"
                f"{f" ({"+" if day > 0 else ""}{day} day)" if day else ""}"
            )

        return formatted_times

    def create_time_info(
        self,
        default_time_now: dt.datetime,
        default_format: str | None,
        user: discord.User | discord.Member | None,
        default_zone: dt.timezone | None,
    ) -> str:
        if not default_zone:
            return (
                f"{f"{user.mention} does" if user else "You do"} not have a default time zone set.\n"
                f"Date: {default_time_now.strftime("%Y-%m-%d")}"
            )

        return (
            f"Date and Time: {default_time_now.strftime(f"%Y-%m-%d at **{default_format}**")}\n"
            f"{f"{user.mention}'s" if user else "Your"} time offset is: {default_time_now.tzname()}"
        )


class Commands(commands.Cog):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.times_message_command = app_commands.ContextMenu(
            name="Show Time Zones", callback=self.ctx_menu_callback_msg
        )
        self.times_user_command = app_commands.ContextMenu(
            name="Show Time Zones", callback=self.ctx_menu_callback
        )
        bot.tree.add_command(self.times_message_command)
        bot.tree.add_command(self.times_user_command)

    @app_commands.command()
    @app_commands.describe(user="Whose time zones you want to see.")
    async def times(
        self, itn: discord.Interaction[Bot], user: discord.User | discord.Member | None
    ):
        """Shows all your time zones."""
        async with self.bot.pool.acquire() as conn:
            time_zones: list[ZoneData] = await conn.fetchall(
                "SELECT * FROM time_zones WHERE user_id = ?",
                user.id if user else itn.user.id,
            )  # type: ignore

        if not time_zones:
            if user is None:
                await itn.response.send_message(
                    "You do not have any time zones setup yet. Use /settings to set your time zones up.",
                    ephemeral=True,
                )
            else:
                await itn.response.send_message(
                    f"{user.mention} does not have their time zones setup yet.",
                    ephemeral=True,
                )
            return

        view = ui.LayoutView()
        view.add_item(TimeContainer(data=time_zones, user=user))
        await itn.response.send_message(view=view, ephemeral=True)

    async def ctx_menu_callback(
        self, itn: discord.Interaction[Bot], member: discord.Member | discord.User
    ):
        async with self.bot.pool.acquire() as conn:
            time_zones: list[ZoneData] = await conn.fetchall(
                "SELECT * FROM time_zones WHERE user_id = ?",
                member.id,
            )  # type: ignore

        if not time_zones:
            await itn.response.send_message(
                f"{member.mention} does not have their time zones setup yet.",
                ephemeral=True,
            )
            return

        view = ui.LayoutView()
        view.add_item(TimeContainer(data=time_zones, user=member))
        await itn.response.send_message(view=view, ephemeral=True)

    async def ctx_menu_callback_msg(
        self, itn: discord.Interaction[Bot], message: discord.Message
    ):
        await self.ctx_menu_callback(itn, message.author)

    @app_commands.command()
    async def settings(self, itn: discord.Interaction[Bot]):
        """Edit your time zones."""
        async with self.bot.pool.acquire() as conn:
            time_zones: list[ZoneData] = await conn.fetchall(
                "SELECT * FROM time_zones WHERE user_id = ?", itn.user.id
            )  # type: ignore

        view = SettingsView(bot=self.bot, zones=time_zones)

        await itn.response.send_message(view=view, ephemeral=True)


async def setup(bot: Bot):
    await bot.add_cog(Commands(bot))
