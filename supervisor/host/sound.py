"""Pulse host control."""
from datetime import timedelta
from enum import Enum
import logging
from typing import Optional

import attr
from pulsectl import Pulse, PulseError, PulseIndexError, PulseOperationFailed

from ..coresys import CoreSys, CoreSysAttributes
from ..exceptions import PulseAudioError
from ..jobs.const import JobExecutionLimit
from ..jobs.decorator import Job

_LOGGER: logging.Logger = logging.getLogger(__name__)

PULSE_NAME = "supervisor"


class StreamType(str, Enum):
    """INPUT/OUTPUT type of source."""

    INPUT = "input"
    OUTPUT = "output"


@attr.s(frozen=True)
class AudioApplication:
    """Represent a application on the stream."""

    name: str = attr.ib()
    index: int = attr.ib()
    stream_index: str = attr.ib()
    stream_type: StreamType = attr.ib()
    volume: float = attr.ib()
    mute: bool = attr.ib()
    addon: str = attr.ib()


@attr.s(frozen=True)
class AudioStream:
    """Represent a input/output stream."""

    name: str = attr.ib()
    index: int = attr.ib()
    description: str = attr.ib()
    volume: float = attr.ib()
    mute: bool = attr.ib()
    default: bool = attr.ib()
    card: Optional[int] = attr.ib()
    applications: list[AudioApplication] = attr.ib()


@attr.s(frozen=True)
class SoundProfile:
    """Represent a Sound Card profile."""

    name: str = attr.ib()
    description: str = attr.ib()
    active: bool = attr.ib()


@attr.s(frozen=True)
class SoundCard:
    """Represent a Sound Card."""

    name: str = attr.ib()
    index: int = attr.ib()
    driver: str = attr.ib()
    profiles: list[SoundProfile] = attr.ib()


class SoundControl(CoreSysAttributes):
    """Pulse control from Host."""

    def __init__(self, coresys: CoreSys) -> None:
        """Initialize PulseAudio sound control."""
        self.coresys: CoreSys = coresys
        self._cards: list[SoundCard] = []
        self._inputs: list[AudioStream] = []
        self._outputs: list[AudioStream] = []
        self._applications: list[AudioApplication] = []

    @property
    def cards(self) -> list[SoundCard]:
        """Return a list of available sound cards and profiles."""
        return self._cards

    @property
    def inputs(self) -> list[AudioStream]:
        """Return a list of available input streams."""
        return self._inputs

    @property
    def outputs(self) -> list[AudioStream]:
        """Return a list of available output streams."""
        return self._outputs

    @property
    def applications(self) -> list[AudioApplication]:
        """Return a list of available application streams."""
        return self._applications

    async def set_default(self, stream_type: StreamType, name: str) -> None:
        """Set a stream to default input/output."""

        def _set_default():
            source = sink = None
            try:
                with Pulse(PULSE_NAME) as pulse:
                    if stream_type == StreamType.INPUT:
                        # Get source and set it as default
                        source = pulse.get_source_by_name(name)
                        pulse.source_default_set(source)
                    else:
                        # Get sink and set it as default
                        sink = pulse.get_sink_by_name(name)
                        pulse.sink_default_set(sink)

            except PulseIndexError as err:
                raise PulseAudioError(
                    f"Can't find {source} stream {name}", _LOGGER.error
                ) from err
            except PulseError as err:
                raise PulseAudioError(
                    f"Can't set {name} as stream: {err}", _LOGGER.error
                ) from err

        # Run and Reload data
        await self.sys_run_in_executor(_set_default)
        await self.update()

    async def set_volume(
        self, stream_type: StreamType, index: int, volume: float, application: bool
    ) -> None:
        """Set a stream to volume input/output/application."""

        def _set_volume():
            try:
                with Pulse(PULSE_NAME) as pulse:
                    if stream_type == StreamType.INPUT:
                        if application:
                            stream = pulse.source_output_info(index)
                        else:
                            stream = pulse.source_info(index)
                    else:
                        if application:
                            stream = pulse.sink_input_info(index)
                        else:
                            stream = pulse.sink_info(index)

                    # Set volume
                    pulse.volume_set_all_chans(stream, volume)
            except PulseIndexError as err:
                raise PulseAudioError(
                    f"Can't find {stream_type} stream {index} (App: {application})",
                    _LOGGER.error,
                ) from err
            except PulseError as err:
                raise PulseAudioError(
                    f"Can't set {index} volume: {err}", _LOGGER.error
                ) from err

        # Run and Reload data
        await self.sys_run_in_executor(_set_volume)
        await self.update()

    async def set_mute(
        self, stream_type: StreamType, index: int, mute: bool, application: bool
    ) -> None:
        """Set a stream to mute input/output/application."""

        def _set_mute():
            try:
                with Pulse(PULSE_NAME) as pulse:
                    if stream_type == StreamType.INPUT:
                        if application:
                            stream = pulse.source_output_info(index)
                        else:
                            stream = pulse.source_info(index)
                    else:
                        if application:
                            stream = pulse.sink_input_info(index)
                        else:
                            stream = pulse.sink_info(index)

                    # Mute stream
                    pulse.mute(stream, mute)
            except PulseIndexError as err:
                raise PulseAudioError(
                    f"Can't find {stream_type} stream {index} (App: {application})",
                    _LOGGER.error,
                ) from err
            except PulseError as err:
                raise PulseAudioError(
                    f"Can't set {index} volume: {err}", _LOGGER.error
                ) from err

        # Run and Reload data
        await self.sys_run_in_executor(_set_mute)
        await self.update()

    async def ativate_profile(self, card_name: str, profile_name: str) -> None:
        """Set a profile to volume input/output."""

        def _activate_profile():
            try:
                with Pulse(PULSE_NAME) as pulse:
                    card = pulse.get_card_by_name(card_name)
                    pulse.card_profile_set(card, profile_name)

            except PulseIndexError as err:
                raise PulseAudioError(
                    f"Can't find {card_name} profile {profile_name}", _LOGGER.error
                ) from err
            except PulseError as err:
                raise PulseAudioError(
                    f"Can't activate {card_name} profile {profile_name}: {err}",
                    _LOGGER.error,
                ) from err

        # Run and Reload data
        await self.sys_run_in_executor(_activate_profile)
        await self.update()

    @Job(limit=JobExecutionLimit.THROTTLE_WAIT, throttle_period=timedelta(seconds=10))
    async def update(self):
        """Update properties over dbus."""
        _LOGGER.info("Updating PulseAudio information")

        def _update():
            try:
                with Pulse(PULSE_NAME) as pulse:
                    server = pulse.server_info()

                    # Update applications
                    self._applications.clear()
                    for application in pulse.sink_input_list():
                        self._applications.append(
                            AudioApplication(
                                application.proplist.get(
                                    "application.name", application.name
                                ),
                                application.index,
                                application.sink,
                                StreamType.OUTPUT,
                                application.volume.value_flat,
                                bool(application.mute),
                                application.proplist.get(
                                    "application.process.machine_id", ""
                                ).replace("-", "_"),
                            )
                        )
                    for application in pulse.source_output_list():
                        self._applications.append(
                            AudioApplication(
                                application.proplist.get(
                                    "application.name", application.name
                                ),
                                application.index,
                                application.source,
                                StreamType.INPUT,
                                application.volume.value_flat,
                                bool(application.mute),
                                application.proplist.get(
                                    "application.process.machine_id", ""
                                ).replace("-", "_"),
                            )
                        )

                    # Update output
                    self._outputs.clear()
                    for sink in pulse.sink_list():
                        self._outputs.append(
                            AudioStream(
                                sink.name,
                                sink.index,
                                sink.description,
                                sink.volume.value_flat,
                                bool(sink.mute),
                                sink.name == server.default_sink_name,
                                sink.card if sink.card != 0xFFFFFFFF else None,
                                [
                                    application
                                    for application in self._applications
                                    if application.stream_index == sink.index
                                    and application.stream_type == StreamType.OUTPUT
                                ],
                            )
                        )

                    # Update input
                    self._inputs.clear()
                    for source in pulse.source_list():
                        # Filter monitor devices out because we did not use it now
                        if source.name.endswith(".monitor"):
                            continue
                        self._inputs.append(
                            AudioStream(
                                source.name,
                                source.index,
                                source.description,
                                source.volume.value_flat,
                                bool(source.mute),
                                source.name == server.default_source_name,
                                source.card if source.card != 0xFFFFFFFF else None,
                                [
                                    application
                                    for application in self._applications
                                    if application.stream_index == source.index
                                    and application.stream_type == StreamType.INPUT
                                ],
                            )
                        )

                    # Update Sound Card
                    self._cards.clear()
                    for card in pulse.card_list():
                        sound_profiles: list[SoundProfile] = []

                        # Generate profiles
                        for profile in card.profile_list:
                            if not profile.available:
                                continue
                            sound_profiles.append(
                                SoundProfile(
                                    profile.name,
                                    profile.description,
                                    profile.name == card.profile_active.name,
                                )
                            )

                        self._cards.append(
                            SoundCard(
                                card.name, card.index, card.driver, sound_profiles
                            )
                        )

            except PulseOperationFailed as err:
                raise PulseAudioError(
                    f"Error while processing pulse update: {err}", _LOGGER.error
                ) from err
            except PulseError as err:
                _LOGGER.debug("Can't update PulseAudio data: %s", err)

        # Run update from pulse server
        await self.sys_run_in_executor(_update)
