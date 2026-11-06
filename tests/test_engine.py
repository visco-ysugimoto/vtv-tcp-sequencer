import asyncio

import pytest

from backend.engine import SequenceEngine
from backend.models import (
    BreakStep,
    CommandStep,
    DelayStep,
    IfStep,
    LoopStep,
    NoteStep,
    ProtocolSettings,
    SequenceRequest,
    VariableStep,
)
from backend.protocol import CommandResult, ProtocolError, VtvTcpClient


async def test_break_exits_nearest_loop() -> None:
    events: list[dict] = []

    async def collect(event: dict) -> None:
        events.append(event)

    client = VtvTcpClient(ProtocolSettings(host="127.0.0.1"))
    engine = SequenceEngine(client, collect, asyncio.Event())
    steps = [LoopStep(type="loop", count=10, steps=[BreakStep(type="break")])]

    await engine.run(steps)

    iterations = [event for event in events if event["type"] == "loop_iteration"]
    assert len(iterations) == 1
    assert any(event["type"] == "loop_break" for event in events)
    assert events[-1]["type"] == "sequence_completed"


async def test_break_outside_loop_is_rejected() -> None:
    async def discard(_event: dict) -> None:
        pass

    client = VtvTcpClient(ProtocolSettings(host="127.0.0.1"))
    engine = SequenceEngine(client, discard, asyncio.Event())

    with pytest.raises(ProtocolError, match="ループの中"):
        await engine.run([BreakStep(type="break")])


async def test_plclink_command_uses_shared_sequence_engine() -> None:
    events: list[dict] = []

    class FakePlcLinkClient:
        settings = ProtocolSettings(
            transport="plclink",
            host="0.0.0.0",
            port=5000,
        )

        async def send_command(
            self,
            command: str,
            expect_result: bool = False,
            result_mode: str = "single",
            *,
            tcp_code: str | None = None,
            arguments: dict | None = None,
            ignore_response: bool = False,
        ) -> CommandResult:
            del expect_result, result_mode, arguments
            assert tcp_code == "RRA"
            assert ignore_response is False
            return CommandResult(command, "AK", ["AK", "result=1"])

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakePlcLinkClient(), collect, asyncio.Event())
    await engine.run([CommandStep(type="command", command="RRA")])

    assert any(
        event["type"] == "tx" and event["display"] == "PLCLINK#9"
        for event in events
    )
    assert [event["response"] for event in events if event["type"] == "rx"] == [
        "AK",
        "result=1",
    ]
    assert events[-1]["type"] == "sequence_completed"


async def test_ignore_response_skips_nk_stop() -> None:
    events: list[dict] = []

    class FakeClient:
        settings = ProtocolSettings(host="127.0.0.1")

        async def send_command(
            self,
            command: str,
            expect_result: bool = False,
            result_mode: str = "single",
            *,
            tcp_code: str | None = None,
            arguments: dict | None = None,
            ignore_response: bool = False,
        ) -> CommandResult:
            del command, expect_result, result_mode, tcp_code, arguments
            assert ignore_response is True
            return CommandResult("RRA", "NK", ["(応答無視)"])

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [CommandStep(type="command", command="RRA", ignore_response=True)]
    )

    assert any(event["type"] == "rx" and event["response"] == "(応答無視)" for event in events)
    assert events[-1]["type"] == "sequence_completed"
    assert isinstance(events[-1]["duration_ms"], int)
    assert events[-1]["last_response"] == "(応答無視)"


async def test_step_events_identify_executed_cards() -> None:
    events: list[dict] = []

    class FakeClient:
        settings = ProtocolSettings(host="127.0.0.1")

        async def send_command(
            self,
            command: str,
            expect_result: bool = False,
            result_mode: str = "single",
            *,
            tcp_code: str | None = None,
            arguments: dict | None = None,
            ignore_response: bool = False,
        ) -> CommandResult:
            del expect_result, result_mode, tcp_code, arguments, ignore_response
            return CommandResult(command, "AK", ["AK"])

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [
            CommandStep(type="command", command="RRA", id="1"),
            IfStep(
                type="if",
                id="if-1",
                source="status",
                operator="equals",
                value="AK",
                then_steps=[
                    CommandStep(type="command", command="RRA", id="then")
                ],
                else_steps=[
                    CommandStep(type="command", command="RRA", id="else")
                ],
            ),
            LoopStep(
                type="loop",
                id="loop-1",
                count=2,
                steps=[DelayStep(type="delay", milliseconds=0, id="wait")],
            ),
        ]
    )

    started = [event for event in events if event["type"] == "step_started"]
    assert [event["id"] for event in started] == [
        "1",
        "if-1",
        "then",
        "loop-1",
        "wait",
        "wait",
    ]
    assert [event["position"] for event in started] == [1, 2, 3, 5, 6, 6]
    assert {event["total"] for event in started} == {6}
    assert started[0]["label"].startswith("RRA")
    assert "else" not in {event["id"] for event in started}
    sent = [event for event in events if event["type"] == "tx" and event["id"] == "1"]
    assert sent and sent[0]["id"] == "1"


async def test_note_is_recorded_without_sending() -> None:
    events: list[dict] = []

    class FakeClient:
        settings = ProtocolSettings(host="127.0.0.1")

        async def send_command(self, *_args, **_kwargs) -> CommandResult:
            raise AssertionError("メモカードは送信しない")

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run([NoteStep(type="note", id="memo", text="BUSY確認")])

    note = next(event for event in events if event["type"] == "note")
    assert note["id"] == "memo"
    assert note["message"] == "BUSY確認"
    assert not any(event["type"] == "tx" for event in events)
    assert events[-1]["type"] == "sequence_completed"


async def test_variable_stores_card_result_for_later_argument() -> None:
    sent: list[str] = []
    events: list[dict] = []

    class FakeClient:
        settings = ProtocolSettings(host="127.0.0.1")

        async def send_command(
            self,
            command: str,
            expect_result: bool = False,
            result_mode: str = "single",
            *,
            tcp_code: str | None = None,
            arguments: dict | None = None,
            ignore_response: bool = False,
        ) -> CommandResult:
            del expect_result, result_mode, tcp_code, arguments, ignore_response
            sent.append(command)
            return CommandResult(command, "AK", ["LOT-9"])

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [
            CommandStep(type="command", command="RRA", id="first"),
            VariableStep(
                type="variable",
                id="lot",
                name="ロット",
                source="card_response",
                card_id="first",
            ),
            CommandStep(
                type="command",
                command="TCA",
                id="second",
                arguments={"camera": 1, "line": 1, "text": ""},
                argument_variables={"text": "ロット"},
            ),
        ]
    )

    stored = next(event for event in events if event["type"] == "variable")
    assert stored["name"] == "ロット"
    assert stored["value"] == "LOT-9"
    assert "LOT-9" in sent[1]


async def test_variable_reads_output_port() -> None:
    events: list[dict] = []

    class Memory:
        def get_bit(self, address: int) -> int:
            return 1 if address == 1026 else 0

    class FakeClient:
        settings = ProtocolSettings(
            host="127.0.0.1",
            transport="plclink",
            plo_address=1024,
            plo_port_count=32,
        )
        memory = Memory()

        async def send_command(self, *_args, **_kwargs) -> CommandResult:
            raise AssertionError("変数カードは送信しない")

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [
            VariableStep(
                type="variable",
                id="port",
                name="信号",
                source="output_port",
                port=3,
            )
        ]
    )

    stored = next(event for event in events if event["type"] == "variable")
    assert stored["value"] == "1"
    assert events[-1]["type"] == "sequence_completed"


async def test_variable_reads_result_data() -> None:
    events: list[dict] = []

    class Memory:
        def read_dword(self, address: int) -> int:
            return {512: 12345, 514: 1500, 516: 2_147_483_646}[address]

    class FakeClient:
        settings = ProtocolSettings(
            host="127.0.0.1",
            transport="plclink",
            result_data_address=512,
            result_data_size=8,
            result_data_decimals=3,
        )
        memory = Memory()

        async def send_command(self, *_args, **_kwargs) -> CommandResult:
            raise AssertionError("変数カードは送信しない")

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [
            VariableStep(
                type="variable",
                id="dec",
                name="個数",
                source="result_data",
                offset=0,
                result_format="dec",
            ),
            VariableStep(
                type="variable",
                id="fixed",
                name="寸法",
                source="result_data",
                offset=2,
                result_format="fixed",
            ),
            VariableStep(
                type="variable",
                id="empty",
                name="空き",
                source="result_data",
                offset=4,
                result_format="hex",
            ),
        ]
    )

    stored = {
        event["name"]: event["value"]
        for event in events
        if event["type"] == "variable"
    }
    assert stored == {"個数": "12345", "寸法": "1.500", "空き": "No Data"}


async def test_variable_reads_result_string() -> None:
    events: list[dict] = []
    # "33484" を high_low でパックしたワード。先頭 dword だけ見ると 876098355 になる。
    packed = [0x3333, 0x3438, 0x3400, 0x0000]

    class Memory:
        def read_words(self, address: int, count: int) -> list[int]:
            assert address == 512
            return packed[:count]

    class FakeClient:
        settings = ProtocolSettings(
            host="127.0.0.1",
            transport="plclink",
            encoding="cp932",
            byte_order="high_low",
            result_data_address=512,
            result_data_size=8,
        )
        memory = Memory()

        async def send_command(self, *_args, **_kwargs) -> CommandResult:
            raise AssertionError("変数カードは送信しない")

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [
            VariableStep(
                type="variable",
                name="文字認識",
                source="result_data",
                offset=0,
                result_format="string",
            )
        ]
    )

    stored = next(event for event in events if event["type"] == "variable")
    assert stored["value"] == "33484"


async def test_variable_reads_field_network_result_data() -> None:
    events: list[dict] = []

    class FakeClient:
        settings = ProtocolSettings(
            host="192.168.0.10",
            transport="field_network",
        )

        def read_input(self) -> bytes:
            data = bytearray(64)
            data[8:12] = bytes([0x2A, 0x00, 0x00, 0x00])
            return bytes(data)

        async def send_command(self, *_args, **_kwargs) -> CommandResult:
            raise AssertionError("変数カードは送信しない")

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakeClient(), collect, asyncio.Event())
    await engine.run(
        [
            VariableStep(
                type="variable",
                name="測定",
                source="result_data",
                offset=0,
                result_format="hex",
            )
        ]
    )

    stored = next(event for event in events if event["type"] == "variable")
    assert stored["value"] == "0x0000002A"


async def test_variable_result_data_on_tcp_fails() -> None:
    async def collect(_event: dict) -> None:
        pass

    engine = SequenceEngine(
        VtvTcpClient(ProtocolSettings(host="127.0.0.1")),
        collect,
        asyncio.Event(),
    )
    with pytest.raises(ProtocolError, match="結果データ出力を直接読めません"):
        await engine.run(
            [
                VariableStep(
                    type="variable",
                    name="測定",
                    source="result_data",
                )
            ]
        )


async def test_variable_without_previous_response_fails() -> None:
    async def collect(_event: dict) -> None:
        pass

    engine = SequenceEngine(
        VtvTcpClient(ProtocolSettings(host="127.0.0.1")),
        collect,
        asyncio.Event(),
    )
    with pytest.raises(ProtocolError, match="直前の応答がありません"):
        await engine.run(
            [
                VariableStep(
                    type="variable",
                    name="ロット",
                    source="last_response",
                )
            ]
        )


def test_variable_round_trip_ignores_old_binding() -> None:
    request = SequenceRequest.model_validate(
        {
            "settings": {"host": "127.0.0.1", "port": 8500},
            "steps": [
                {
                    "type": "variable",
                    "id": "v1",
                    "name": "ロット",
                    "source": "card_status",
                    "card_id": "c1",
                },
                {
                    "type": "command",
                    "command": "TCA",
                    "arguments": {"text": ""},
                    "bindings": {"text": "last_response"},
                    "argument_variables": {"text": "ロット"},
                },
            ],
        }
    )
    assert isinstance(request.steps[0], VariableStep)
    assert request.steps[0].offset == 0
    assert request.steps[0].result_format == "dec"
    command = request.steps[1]
    assert isinstance(command, CommandStep)
    assert command.argument_variables["text"] == "ロット"
    assert not hasattr(command, "bindings")
