import Foundation

/// What one `claude -p --output-format stream-json` run tells the chat.
public enum ChatEvent: Sendable, Equatable {
    case session(String)
    case text(String)
    /// A short line for a tool call ("$ ls", "Edit app.py").
    case tool(String)
    case done(ok: Bool, text: String)
}

/// Parses the stream-json lines of Claude Code.
public enum ClaudeStream {
    public static func parse(_ line: String) -> [ChatEvent] {
        guard let data = line.data(using: .utf8),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let type = obj["type"] as? String
        else { return [] }
        switch type {
        case "system":
            guard obj["subtype"] as? String == "init", let id = obj["session_id"] as? String else { return [] }
            return [.session(id)]
        case "assistant":
            // Messages of subagents have a parent tool; show only the main thread.
            if let parent = obj["parent_tool_use_id"] as? String, !parent.isEmpty { return [] }
            let content = (obj["message"] as? [String: Any])?["content"] as? [[String: Any]] ?? []
            return content.compactMap { block in
                switch block["type"] as? String {
                case "text":
                    let t = (block["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    return t.isEmpty ? nil : .text(t)
                case "tool_use":
                    return .tool(toolLine(block["name"] as? String ?? "?", block["input"] as? [String: Any] ?? [:]))
                default:
                    return nil
                }
            }
        case "result":
            let isError = obj["is_error"] as? Bool ?? false
            var text = obj["result"] as? String ?? ""
            if isError && text.isEmpty { text = obj["subtype"] as? String ?? "erro" }
            return [.done(ok: !isError, text: text)]
        default:
            return []
        }
    }

    static func toolLine(_ name: String, _ input: [String: Any]) -> String {
        func s(_ key: String) -> String? {
            guard let v = input[key] as? String, !v.isEmpty else { return nil }
            return v
        }
        let detail: String?
        switch name {
        case "Bash": detail = s("command").map { "$ " + $0 }
        case "Read", "Edit", "Write", "NotebookEdit": detail = s("file_path").map { ($0 as NSString).lastPathComponent }
        case "Grep", "Glob": detail = s("pattern")
        case "WebFetch": detail = s("url")
        case "WebSearch": detail = s("query")
        case "Agent", "Task": detail = s("description")
        case "Skill": detail = s("skill")
        default: detail = nil
        }
        guard let detail else { return name }
        let line = detail.split(separator: "\n").first.map(String.init) ?? detail
        let short = line.count > 120 ? String(line.prefix(120)) + "…" : line
        return name == "Bash" ? short : "\(name) \(short)"
    }
}

/// One headless Claude Code turn. Uses the Claude login of this Mac (your subscription).
public final class ClaudeRun: @unchecked Sendable {
    private let lock = NSLock()
    private var pid: pid_t = 0
    private var stopped = false

    public init() {}

    /// The `claude` program: `CLAUDE_BIN`, the login PATH, or ~/.local/bin/claude.
    public static var binary: String? {
        if let p = ProcessInfo.processInfo.environment["CLAUDE_BIN"], !p.isEmpty { return Paths.expand(p) }
        if let p = Shell.which("claude") { return p }
        let local = Paths.home + "/.local/bin/claude"
        return FileManager.default.isExecutableFile(atPath: local) ? local : nil
    }

    /// Our environment without the variables that tie a child to a parent Claude Code session
    /// (when the app was started from inside Claude Code), and with the login PATH.
    static func cleanEnv() -> [String: String] {
        var env = ProcessInfo.processInfo.environment.filter { k, _ in
            !(k == "CLAUDECODE" || k.hasPrefix("CLAUDE_CODE_") || k == "CLAUDE_PID" || k == "CLAUDE_EFFORT")
        }
        env["PATH"] = Shell.loginPath
        return env
    }

    public static func arguments(prompt: String, session: String?, addDirs: [String], systemPrompt: String) -> [String] {
        var args = ["-p", prompt, "--output-format", "stream-json", "--verbose",
                    // Nobody can answer a permission prompt here: auto mode decides each tool call.
                    "--permission-mode", "auto",
                    "--append-system-prompt", systemPrompt]
        for d in addDirs { args += ["--add-dir", d] }
        if let session { args += ["--resume", session] }
        return args
    }

    public func start(prompt: String, session: String?, cwd: String, addDirs: [String], systemPrompt: String) -> AsyncStream<ChatEvent> {
        AsyncStream { cont in
            guard let bin = Self.binary else {
                cont.yield(.done(ok: false, text: "Não achei o Claude Code (claude). Instale e faça login no Terminal."))
                cont.finish()
                return
            }
            Paths.ensureDir(cwd)
            var outFDs: [Int32] = [0, 0], errFDs: [Int32] = [0, 0]
            guard pipe(&outFDs) == 0, pipe(&errFDs) == 0 else {
                cont.yield(.done(ok: false, text: "pipe falhou"))
                cont.finish()
                return
            }
            let argv = [bin] + Self.arguments(prompt: prompt, session: session, addDirs: addDirs, systemPrompt: systemPrompt)
            let child: pid_t
            do {
                child = try Spawn.spawn(argv, cwd: cwd, env: Self.cleanEnv(),
                                        stdout: .fd(outFDs[1]), stderr: .fd(errFDs[1]), newSession: false)
            } catch {
                [outFDs[0], outFDs[1], errFDs[0], errFDs[1]].forEach { close($0) }
                cont.yield(.done(ok: false, text: error.localizedDescription))
                cont.finish()
                return
            }
            close(outFDs[1]); close(errFDs[1])
            lock.lock(); pid = child; let alreadyStopped = stopped; lock.unlock()
            if alreadyStopped { kill(-child, SIGTERM) }

            let errData = LockedData()
            let errHandle = FileHandle(fileDescriptor: errFDs[0], closeOnDealloc: true)
            let errDone = DispatchSemaphore(value: 0)
            DispatchQueue.global().async {
                errData.set(errHandle.readDataToEndOfFile())
                errDone.signal()
            }
            let outHandle = FileHandle(fileDescriptor: outFDs[0], closeOnDealloc: true)
            Thread.detachNewThread { [self] in
                var buffer = Data()
                var finished = false
                func emit(_ line: Data) {
                    for e in ClaudeStream.parse(String(decoding: line, as: UTF8.self)) {
                        if case .done = e { finished = true }
                        cont.yield(e)
                    }
                }
                while true {
                    let chunk = outHandle.availableData
                    if chunk.isEmpty { break }
                    buffer.append(chunk)
                    while let nl = buffer.firstIndex(of: 0x0A) {
                        emit(buffer[buffer.startIndex..<nl])
                        buffer.removeSubrange(buffer.startIndex...nl)
                    }
                }
                if !buffer.isEmpty { emit(buffer) }
                errDone.wait()
                let code = Spawn.wait(child)
                lock.lock(); pid = 0; let wasStopped = stopped; lock.unlock()
                if !finished {
                    let err = String(decoding: errData.get(), as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
                    let tail = err.split(separator: "\n").suffix(4).joined(separator: "\n")
                    let text = wasStopped ? "Parado." : (tail.isEmpty ? "Claude saiu com código \(code)." : tail)
                    cont.yield(.done(ok: false, text: text))
                }
                cont.finish()
            }
            cont.onTermination = { [weak self] _ in self?.stop() }
        }
    }

    /// Stops the run and everything it started (the child leads its own process group).
    public func stop() {
        lock.lock()
        stopped = true
        let p = pid
        lock.unlock()
        guard p > 0 else { return }
        kill(-p, SIGTERM)
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) {
            if CommandRunner.groupAlive(p) { kill(-p, SIGKILL) }
        }
    }
}
