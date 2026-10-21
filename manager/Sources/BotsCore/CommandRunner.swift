import Foundation

/// Runs a `command` service detached from the app, in its own session and process group,
/// so it keeps running when the app quits. PID in `run/<id>.pid`, output in `logs/<id>.log`.
enum CommandRunner {
    static func pidFile(_ s: ServiceConfig) -> String { "\(Paths.runDir)/\(s.id).pid" }
    static func exitFile(_ s: ServiceConfig) -> String { "\(Paths.runDir)/\(s.id).exit" }
    static func defaultLog(_ s: ServiceConfig) -> String { "\(Paths.logsDir)/\(s.id).log" }
    static func logPath(_ s: ServiceConfig) -> String { s.log.map { Paths.expand($0) } ?? defaultLog(s) }

    static func readInt(_ path: String) -> Int32? {
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        return Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    /// The PID group we started, if it still has a live process.
    static func livePID(_ s: ServiceConfig) -> Int32? {
        guard let pid = readInt(pidFile(s)), pid > 1 else { return nil }
        return groupAlive(pid) ? pid : nil
    }

    /// True when any process is left in group `pgid` (the PID we spawned with setsid).
    static func groupAlive(_ pgid: Int32) -> Bool {
        if kill(-pgid, 0) == 0 || errno == EPERM {
            // A zombie leader still answers kill(); check it is a real process of that group.
            return isRealProcess(pgid) || hasOtherMembers(pgid)
        }
        return false
    }

    static func isRealProcess(_ pid: Int32) -> Bool {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size else { return false }
        return info.pbi_status != UInt32(SZOMB) && Int32(bitPattern: info.pbi_pgid) == pid
    }

    static func hasOtherMembers(_ pgid: Int32) -> Bool {
        var pids = [Int32](repeating: 0, count: 64)
        let n = proc_listpids(UInt32(PROC_PGRP_ONLY), UInt32(pgid), &pids, Int32(pids.count * 4))
        guard n > 0 else { return false }
        return pids.prefix(Int(n) / 4).contains { $0 > 0 && $0 != pgid }
    }

    static func status(_ s: ServiceConfig) -> ServiceStatus {
        if let pid = livePID(s) {
            return ServiceStatus(state: .running, detail: "rodando · pid \(pid)", pid: pid, canStop: true, canStart: false)
        }
        if let code = readInt(exitFile(s)), code != 0 {
            return ServiceStatus(state: .failed, detail: "parou com erro \(code)", canStop: false, canStart: true)
        }
        return ServiceStatus(state: .stopped, detail: "parado", canStop: s.stopCommand != nil, canStart: true)
    }

    static func start(_ s: ServiceConfig) throws {
        guard let command = s.command, !command.isEmpty else { throw ActionError("falta \"command\"") }
        if livePID(s) != nil { return }
        Paths.ensureDir(Paths.runDir)
        let log = logPath(s)
        Paths.ensureDir((log as NSString).deletingLastPathComponent)
        let cwd = s.cwdPath ?? Paths.home
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: cwd, isDirectory: &isDir), isDir.boolValue else {
            throw ActionError("pasta não existe: \(cwd)")
        }
        try? FileManager.default.removeItem(atPath: exitFile(s))

        var env = ProcessInfo.processInfo.environment
        for (k, v) in s.env ?? [:] { env[k] = Paths.expand(v) }
        env["BOTS_MANAGER_EXIT_FILE"] = exitFile(s)
        env["BOTS_MANAGER_SERVICE"] = s.id

        let stamp = ISO8601DateFormatter().string(from: Date())
        appendLine(log, "\n=== \(stamp) bots-manager: iniciando \(s.id): \(command)\n")

        // The EXIT trap keeps zsh as the parent and saves the exit code when the command ends
        // (also after an "exit N" inside the command).
        let script = "trap 'print -r -- $? >| \"$BOTS_MANAGER_EXIT_FILE\"' EXIT\n\(command)"
        let pid = try Spawn.spawn(["/bin/zsh", "-lc", script], cwd: cwd, env: env,
                                  stdout: .appendFile(log), stderr: nil, newSession: true)
        do {
            try "\(pid)\n".write(toFile: pidFile(s), atomically: true, encoding: .utf8)
        } catch {
            throw ActionError("não salvou o pid: \(error.localizedDescription)")
        }
        // Reap the child when it ends, so it does not stay a zombie of this process.
        Thread.detachNewThread { Spawn.wait(pid) }
        // Fail fast if the command dies at once (bad command, port in use...).
        for _ in 0..<6 {
            usleep(100_000)
            if !groupAlive(pid) { break }
        }
        if !groupAlive(pid) {
            try? FileManager.default.removeItem(atPath: pidFile(s))
            let code = readInt(exitFile(s)).map { "erro \($0)" } ?? "saiu"
            throw ActionError("parou logo ao iniciar (\(code)); veja o log")
        }
    }

    static func stop(_ s: ServiceConfig) throws {
        if let pid = livePID(s) {
            kill(-pid, SIGTERM)
            let deadline = Date().addingTimeInterval(5)
            while groupAlive(pid) && Date() < deadline { usleep(100_000) }
            if groupAlive(pid) {
                kill(-pid, SIGKILL)
                usleep(200_000)
            }
            appendLine(logPath(s), "=== bots-manager: parado\n")
        }
        try? FileManager.default.removeItem(atPath: pidFile(s))
        try? FileManager.default.removeItem(atPath: exitFile(s))
        if let stop = s.stopCommand, !stop.isEmpty {
            var env: [String: String] = [:]
            for (k, v) in s.env ?? [:] { env[k] = Paths.expand(v) }
            let r = Shell.zsh(stop, cwd: s.cwdPath, env: env)
            if !r.ok { throw ActionError("stop_command: \(r.message)") }
        }
    }

    static func appendLine(_ path: String, _ text: String) {
        guard let data = text.data(using: .utf8) else { return }
        if let h = FileHandle(forWritingAtPath: path) {
            h.seekToEndOfFile()
            h.write(data)
            try? h.close()
        } else {
            FileManager.default.createFile(atPath: path, contents: data)
        }
    }
}
