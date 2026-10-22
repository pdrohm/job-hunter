import Foundation
import Testing
@testable import BotsCore

@Suite struct LaunchdTests {
    let sample = """
    gui/501/com.example.bot = {
    \tactive count = 1
    \tpath = /Users/me/Library/LaunchAgents/com.example.bot.plist
    \ttype = LaunchAgent
    \tstate = running

    \tprogram = /usr/bin/python3
    \truns = 3
    \tpid = 4242
    \tlast exit code = 1
    \tresource coalition = {
    \t\tID = 71480
    \t\tstate = active
    \t}
    }
    """

    @Test func parsesTopLevelKeysOnly() {
        let info = LaunchdInfo.parse(sample)
        #expect(info.state == "running")
        #expect(info.pid == 4242)
        #expect(info.lastExitCode == 1)
        #expect(info.runs == 3)
    }

    @Test func neverExitedIsNil() {
        let info = LaunchdInfo.parse("x = {\n\tstate = not running\n\tlast exit code = (never exited)\n}")
        #expect(info.state == "not running")
        #expect(info.pid == nil)
        #expect(info.lastExitCode == nil)
    }

    @Test func scheduleTexts() {
        #expect(LaunchdPlist.from(["StartInterval": 7200]).schedule == "a cada 2 h")
        #expect(LaunchdPlist.from(["StartInterval": 600]).schedule == "a cada 10 min")
        #expect(LaunchdPlist.from(["StartCalendarInterval": ["Hour": 8, "Minute": 0]]).schedule == "08:00")
        #expect(LaunchdPlist.from(["StartCalendarInterval": [["Hour": 8, "Minute": 30, "Weekday": 1]]]).schedule == "seg 08:30")
        #expect(LaunchdPlist.from(["KeepAlive": true]).schedule == nil)
        #expect(LaunchdPlist.from(["KeepAlive": ["SuccessfulExit": false]]).keepAlive)
    }
}

@Suite struct ConfigTests {
    @Test func parsesAndGroupsInFileOrder() throws {
        let json = """
        {"services": [
          {"id": "a", "name": "A", "group": "Bots", "kind": "launchd", "label": "x.a"},
          {"id": "b", "name": "B", "group": "Web", "kind": "command", "command": "npm start",
           "url": "http://127.0.0.1:3000", "env": {"PORT": "3000"}, "stop_command": "true"},
          {"id": "c", "group": "Bots", "kind": "docker", "compose_file": "infra/compose.yml", "cwd": "/tmp/p"}
        ]}
        """
        let services = try ConfigLoader.parse(Data(json.utf8))
        #expect(services.count == 3)
        #expect(services[1].stopCommand == "true")
        #expect(services[2].name == "c")
        #expect(services[2].composePath == "/tmp/p/infra/compose.yml")
        #expect(services[0].plistPath == NSHomeDirectory() + "/Library/LaunchAgents/x.a.plist")
        let groups = ConfigLoader.groups(services)
        #expect(groups.map(\.name) == ["Bots", "Web"])
        #expect(groups[0].services.map(\.id) == ["a", "c"])
    }

    @Test func rejectsDuplicateIDs() {
        let json = #"{"services": [{"id": "a", "kind": "command", "command": "x"}, {"id": "a", "kind": "command", "command": "y"}]}"#
        #expect(throws: ConfigError.self) { try ConfigLoader.parse(Data(json.utf8)) }
    }

    @Test func reportsMissingField() {
        let json = #"{"services": [{"name": "no id", "kind": "command"}]}"#
        #expect(throws: ConfigError.self) { try ConfigLoader.parse(Data(json.utf8)) }
    }

    @Test func templateIsValid() throws {
        #expect(try ConfigLoader.parse(Data(ConfigLoader.template.utf8)).count == 1)
    }

    @Test func expandsHomeAndVariables() {
        let env = ["PATH": "/usr/bin:/bin", "X": "1"]
        #expect(Paths.expand("~/a", env: env) == NSHomeDirectory() + "/a")
        #expect(Paths.expand("/opt/bin:$PATH", env: env) == "/opt/bin:/usr/bin:/bin")
        #expect(Paths.expand("${X}-$MISSING-$", env: env) == "1--$")
    }

    @Test func problemNamesMissingField() {
        var s = ServiceConfig(id: "x", name: "X", group: "G", kind: .command)
        #expect(s.problem != nil)
        s.command = "sleep 1"
        #expect(s.problem == nil)
    }
}

@Suite struct DockerTests {
    @Test func parsesArrayAndLines() {
        let array = #"[{"Name":"a","Service":"a","State":"running"},{"Name":"b","Service":"b","State":"exited"}]"#
        #expect(Docker.parsePS(array).map(\.state) == ["running", "exited"])
        let lines = "{\"Name\":\"a\",\"State\":\"running\"}\n{\"Name\":\"b\",\"State\":\"running\"}\n"
        #expect(Docker.parsePS(lines).count == 2)
        #expect(Docker.parsePS("").isEmpty)
    }
}

/// Runs real detached processes (sleep / sh) in a temp BOTS_MANAGER_HOME.
@Suite(.serialized) struct CommandTests {
    let dir: String

    init() {
        dir = NSTemporaryDirectory() + "bots-manager-tests-\(UUID().uuidString)"
        Paths.ensureDir(dir)
        setenv("BOTS_MANAGER_HOME", dir, 1)
    }

    func service(_ id: String, _ command: String) -> ServiceConfig {
        var s = ServiceConfig(id: id, name: id, group: "T", kind: .command)
        s.command = command
        s.cwd = dir
        s.env = ["GREETING": "oi"]
        return s
    }

    @Test func startStatusStop() throws {
        let s = service("sleeper", "echo $GREETING; sleep 30")
        try ServiceController.perform(.start, s)
        let running = ServiceController.status(s)
        #expect(running.state == .running)
        let pid = try #require(running.pid)
        #expect(getpgid(pid) == pid)  // own process group
        try ServiceController.perform(.stop, s)
        #expect(ServiceController.status(s).state == .stopped)
        #expect(kill(-pid, 0) != 0)
        let log = LogFile.tail(dir + "/logs/sleeper.log") ?? ""
        #expect(log.contains("oi"))
    }

    @Test func exitCodeIsReported() throws {
        let s = service("quitter", "sleep 0.8; exit 4")
        try ServiceController.perform(.start, s)
        for _ in 0..<40 where ServiceController.status(s).state == .running { usleep(100_000) }
        let st = ServiceController.status(s)
        #expect(st.state == .failed)
        #expect(st.detail == "parou com erro 4")
    }

    @Test func badCommandFailsFast() {
        let s = service("bad", "no_such_command_bots_manager")
        #expect(throws: ActionError.self) { try ServiceController.perform(.start, s) }
    }

    @Test func shellRunCapturesOutput() {
        let r = Shell.run("/bin/sh", ["-c", "echo out; echo err >&2; exit 3"])
        #expect(r.status == 3)
        #expect(r.stdout == "out\n")
        #expect(r.stderr == "err\n")
        let slow = Shell.run("/bin/sleep", ["5"], timeout: 0.5)
        #expect(!slow.ok)
        #expect(slow.stderr.contains("demorou"))
    }

    @Test func tailKeepsLastLines() throws {
        let path = dir + "/tail.txt"
        try (1...500).map(String.init).joined(separator: "\n").write(toFile: path, atomically: true, encoding: .utf8)
        let t = try #require(LogFile.tail(path, lines: 3))
        #expect(t == "498\n499\n500")
    }
}

@Suite struct ClaudeStreamTests {
    @Test func initGivesSession() {
        let line = #"{"type":"system","subtype":"init","session_id":"abc","tools":[]}"#
        #expect(ClaudeStream.parse(line) == [.session("abc")])
    }

    @Test func hookLinesAreIgnored() {
        let line = #"{"type":"system","subtype":"hook_started","session_id":"abc"}"#
        #expect(ClaudeStream.parse(line).isEmpty)
        #expect(ClaudeStream.parse("not json").isEmpty)
    }

    @Test func assistantTextAndTools() {
        let line = #"{"type":"assistant","parent_tool_use_id":null,"message":{"content":[{"type":"text","text":" Oi \n"},{"type":"tool_use","name":"Bash","input":{"command":"echo hi\nls"}},{"type":"tool_use","name":"Edit","input":{"file_path":"/a/b/app.py"}},{"type":"tool_use","name":"Mystery","input":{}}]}}"#
        #expect(ClaudeStream.parse(line) == [.text("Oi"), .tool("$ echo hi"), .tool("Edit app.py"), .tool("Mystery")])
    }

    @Test func subagentMessagesAreHidden() {
        let line = #"{"type":"assistant","parent_tool_use_id":"toolu_1","message":{"content":[{"type":"text","text":"inner"}]}}"#
        #expect(ClaudeStream.parse(line).isEmpty)
    }

    @Test func result() {
        #expect(ClaudeStream.parse(#"{"type":"result","is_error":false,"result":"ok"}"#) == [.done(ok: true, text: "ok")])
        #expect(ClaudeStream.parse(#"{"type":"result","is_error":true,"subtype":"error_max_turns"}"#)
            == [.done(ok: false, text: "error_max_turns")])
    }

    @Test func resumeArgs() {
        let a = ClaudeRun.arguments(prompt: "hi", session: "s1", addDirs: ["/x"], systemPrompt: "sys")
        #expect(a.contains("--resume") && a.contains("s1"))
        #expect(a.firstIndex(of: "--add-dir").map { a[$0 + 1] } == "/x")
        #expect(!ClaudeRun.arguments(prompt: "hi", session: nil, addDirs: [], systemPrompt: "").contains("--resume"))
    }
}
