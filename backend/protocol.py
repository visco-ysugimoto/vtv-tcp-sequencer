from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .models import ProtocolSettings

SEPARATORS = {
    "space": " ",
    "comma": ",",
    "tab": "\t",
    "underscore": "_",
    "hyphen": "-",
    "none": "",
}


class ProtocolError(RuntimeError):
    """VTV-9000 との通信プロトコルが成立しなかった場合の例外。"""


@dataclass(slots=True)
class CommandResult:
    command: str
    status: str
    responses: list[str]

    @property
    def response(self) -> str:
        return "\n".join(self.responses)


def xor_checksum(data: bytes) -> str:
    value = 0
    for byte in data:
        value ^= byte
    return f"{value:02X}"


def add_checksum(payload: str, separator: str, encoding: str) -> str:
    prefix = f"{payload}{separator}"
    return f"{prefix}{xor_checksum(prefix.encode(encoding))}"


def remove_and_verify_checksum(
    line: str, separator: str, encoding: str
) -> str:
    if not separator:
        if len(line) < 2:
            raise ProtocolError("チェックサムがありません")
        payload, received = line[:-2], line[-2:]
        calculated = xor_checksum(payload.encode(encoding))
        if received.upper() != calculated:
            raise ProtocolError(
                f"チェックサム不一致: 受信={received}, 計算={calculated}"
            )
        return payload

    marker = line.rfind(separator)
    if marker < 0 or len(line[marker + len(separator) :]) != 2:
        raise ProtocolError("チェックサムの形式が不正です")
    payload_with_separator = line[: marker + len(separator)]
    received = line[marker + len(separator) :]
    calculated = xor_checksum(payload_with_separator.encode(encoding))
    if received.upper() != calculated:
        raise ProtocolError(
            f"チェックサム不一致: 受信={received}, 計算={calculated}"
        )
    return line[:marker]


class VtvTcpClient:
    def __init__(self, settings: ProtocolSettings):
        self.settings = settings
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> VtvTcpClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.settings.host, self.settings.port),
                timeout=self.settings.timeout,
            )
        except (TimeoutError, OSError) as exc:
            raise ProtocolError(f"接続できません: {exc}") from exc

    async def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
        self.reader = None
        self.writer = None

    async def send_command(
        self,
        command: str,
        expect_result: bool = False,
        result_mode: str = "single",
    ) -> CommandResult:
        if self.reader is None or self.writer is None:
            raise ProtocolError("装置に接続されていません")

        encoded = command.encode(self.settings.encoding)
        self.writer.write(encoded + b"\r")
        try:
            await asyncio.wait_for(
                self.writer.drain(), timeout=self.settings.timeout
            )
        except (TimeoutError, OSError) as exc:
            raise ProtocolError(f"送信に失敗しました: {exc}") from exc

        responses: list[str] = []
        status = "AK" if not self.settings.input_response else ""
        if self.settings.input_response:
            line = await self._read_line()
            assert line is not None
            responses.append(line)
            status = self._status_from(line)
            if status in {"NK", "ER"}:
                return CommandResult(command, status, responses)
            if status != "AK":
                raise ProtocolError(f"不明な入力応答です: {line}")

        if expect_result:
            line = await self._read_line()
            assert line is not None
            responses.append(line)
            if result_mode == "until_idle":
                while True:
                    line = await self._read_line(
                        timeout=min(self.settings.timeout, 0.2),
                        timeout_is_end=True,
                    )
                    if line is None:
                        break
                    responses.append(line)

        return CommandResult(command, status, responses)

    async def _read_line(
        self,
        timeout: float | None = None,
        timeout_is_end: bool = False,
    ) -> str | None:
        assert self.reader is not None
        terminator = (
            b"\r\n" if self.settings.output_terminator == "CRLF" else b"\r"
        )
        try:
            raw = await asyncio.wait_for(
                self.reader.readuntil(terminator),
                timeout=self.settings.timeout if timeout is None else timeout,
            )
        except TimeoutError as exc:
            if timeout_is_end:
                return None
            raise ProtocolError(
                f"{self.settings.timeout:g}秒以内に応答がありません"
            ) from exc
        except asyncio.IncompleteReadError as exc:
            raise ProtocolError("応答の途中で接続が切断されました") from exc
        except (asyncio.LimitOverrunError, OSError) as exc:
            raise ProtocolError(f"受信に失敗しました: {exc}") from exc

        raw = raw[: -len(terminator)]
        try:
            line = raw.decode(self.settings.encoding)
        except UnicodeDecodeError as exc:
            raise ProtocolError("応答を指定文字コードで解釈できません") from exc

        if self.settings.checksum:
            separator = SEPARATORS[self.settings.separator]
            line = remove_and_verify_checksum(
                line, separator, self.settings.encoding
            )
        return line

    @staticmethod
    def _status_from(line: str) -> str:
        return line.strip().split(maxsplit=1)[0].upper()
