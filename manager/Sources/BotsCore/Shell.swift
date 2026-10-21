import Foundation

public struct ShellResult: Sendable {
    public let status: Int32
    public let stdout: String
    public let stderr: String
    public var ok: Bool { status == 0 }
    /// The most useful line to show when the command failed.
    public var message: String {
        let text = (stderr.isEmpty ? stdout : stderr).trimmingCharacters(in: .whitespacesAndNewlines)
        let last = text.split(separator: "\n").last.map(String.init) ?? ""
        return last.isEmpty ? "saiu com código \(status)" : last
    }
}

final class LockedData: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    func set(_ d: Data) { lock.lock(); data = d; lock.unlock() }
    func get() -> Data { lock.lock(); defer { lock.unlock() }; return data }
}

public enum Shell {
    /// Runs a program and waits for it (blocking). Kills it (and its children) after `timeout` seconds.
    /// Uses posix_spawn with a clean signal mask: Foundation's Process, called from a GCD thread,
    /// passes that thread's blocked signals on, and some Go tools (docker) then hang.
    @discardableResult
    public static func run(
        _ executable: String,
        _ args: [String],
        cwd: String? = nil,
        env: [String: String]? = nil,
        timeout: TimeInterval = 30
    ) -> ShellResult {
        var outFDs: [Int32] = [0, 0], errFDs: [Int32] = [0, 0]
        guard pipe(&outFDs) == 0 else { return ShellResult(status: -1, stdout: "", stderr: "pipe falhou") }
        guard pipe(&errFDs) == 0 else {
            close(outFDs[0]); close(outFDs[1])
            return ShellResult(status: -1, stdout: "", stderr: "pipe falhou")
        }
        let pid: pid_t
        do {
            pid = try Spawn.spawn(
                [executable] + args, cwd: cwd, env: env ?? ProcessInfo.processInfo.environment,
                stdout: .fd(outFDs[1]), stderr: .fd(errFDs[1]), newSession: false
            )
        } catch {
            [outFDs[0], outFDs[1], errFDs[0], errFDs[1]].forEach { close($0) }
            return ShellResult(status: -1, stdout: "", stderr: error.localizedDescription)
        }
        close(outFDs[1]); close(errFDs[1])

        let errData = LockedData()
        let group = DispatchGroup()
        group.enter()
        let errHandle = FileHandle(fileDescriptor: errFDs[0], closeOnDealloc: true)
        DispatchQueue.global().async {
            errData.set(errHandle.readDataToEndOfFile())
            group.leave()
        }
        let timedOut = LockedData()
        let timer = DispatchWorkItem {
            timedOut.set(Data([1]))
            kill(-pid, SIGKILL)  // the child leads its own process group
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: timer)
        let outData = FileHandle(fileDescriptor: outFDs[0], closeOnDealloc: true).readDataToEndOfFile()
        group.wait()
        let status = Spawn.wait(pid)
        timer.cancel()
        var stderr = String(decoding: errData.get(), as: UTF8.self)
        if timedOut.get() == Data([1]) { stderr += "\ndemorou mais de \(Int(timeout)) s e foi parado" }
        return ShellResult(status: status, stdout: String(decoding: outData, as: UTF8.self), stderr: stderr)
    }

    /// Runs a line in the user's login shell (`/bin/zsh -lc`), like a Terminal would.
    @discardableResult
    public static func zsh(_ line: String, cwd: String? = nil, env: [String: String] = [:], timeout: TimeInterval = 120) -> ShellResult {
        var full = ProcessInfo.processInfo.environment
        for (k, v) in env { full[k] = v }
        return run("/bin/zsh", ["-lc", line], cwd: cwd, env: full, timeout: timeout)
    }

    /// The PATH of the user's login shell (Finder-launched apps get a short PATH). Cached.
    public static let loginPath: String = {
        let r = run("/bin/zsh", ["-lc", "print -r -- $PATH"], timeout: 10)
        let p = r.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        let base = r.ok && !p.isEmpty ? p : "/usr/bin:/bin:/usr/sbin:/sbin"
        // Docker Desktop and Homebrew live here even when the profile does not add them.
        var parts = base.split(separator: ":").map(String.init)
        for extra in ["/opt/homebrew/bin", "/usr/local/bin"] where !parts.contains(extra) { parts.append(extra) }
        return parts.joined(separator: ":")
    }()

    /// Finds a program in the login PATH.
    public static func which(_ name: String) -> String? {
        for dir in loginPath.split(separator: ":") {
            let p = "\(dir)/\(name)"
            if FileManager.default.isExecutableFile(atPath: p) { return p }
        }
        return nil
    }
}

/// Runs blocking work on a background queue, so async callers (and the UI) never wait on it.
public func offMain<T: Sendable>(_ work: @escaping @Sendable () -> T) async -> T {
    await withCheckedContinuation { cont in
        DispatchQueue.global(qos: .userInitiated).async { cont.resume(returning: work()) }
    }
}

/// posix_spawn helpers shared by `Shell.run` and the detached command services.
public enum Spawn {
    public enum Output {
        case fd(Int32)
        case appendFile(String)
    }

    /// Starts `argv` with stdin from /dev/null, default signal handlers and an empty signal mask.
    /// `newSession`: setsid (own session and group, survives the app). Otherwise: own process group.
    /// No other open files leak into the child (POSIX_SPAWN_CLOEXEC_DEFAULT).
    public static func spawn(_ argv: [String], cwd: String?, env: [String: String],
                             stdout: Output, stderr: Output?, newSession: Bool) throws -> pid_t {
        var attr: posix_spawnattr_t?
        posix_spawnattr_init(&attr)
        defer { posix_spawnattr_destroy(&attr) }
        var allSignals = sigset_t()
        sigfillset(&allSignals)
        var noSignals = sigset_t()
        sigemptyset(&noSignals)
        posix_spawnattr_setsigdefault(&attr, &allSignals)
        posix_spawnattr_setsigmask(&attr, &noSignals)
        var flags = Int32(POSIX_SPAWN_CLOEXEC_DEFAULT) | Int32(POSIX_SPAWN_SETSIGDEF) | Int32(POSIX_SPAWN_SETSIGMASK)
        if newSession {
            flags |= Int32(POSIX_SPAWN_SETSID)
        } else {
            flags |= Int32(POSIX_SPAWN_SETPGROUP)
            posix_spawnattr_setpgroup(&attr, 0)
        }
        posix_spawnattr_setflags(&attr, Int16(flags))

        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        func wire(_ out: Output, to target: Int32) {
            switch out {
            case .fd(let fd): posix_spawn_file_actions_adddup2(&actions, fd, target)
            case .appendFile(let path):
                posix_spawn_file_actions_addopen(&actions, target, path, O_WRONLY | O_CREAT | O_APPEND, 0o644)
            }
        }
        wire(stdout, to: 1)
        if let stderr { wire(stderr, to: 2) } else { posix_spawn_file_actions_adddup2(&actions, 1, 2) }
        if let cwd { posix_spawn_file_actions_addchdir_np(&actions, cwd) }

        let cArgs = argv.map { strdup($0) } + [nil]
        let cEnv = env.map { strdup("\($0.key)=\($0.value)") } + [nil]
        defer {
            cArgs.forEach { free($0) }
            cEnv.forEach { free($0) }
        }
        var pid: pid_t = 0
        let rc = posix_spawn(&pid, argv[0], &actions, &attr, cArgs, cEnv)
        guard rc == 0 else { throw ActionError("não iniciou \(argv[0]): \(String(cString: strerror(rc)))") }
        return pid
    }

    /// Waits for `pid`. Returns the exit code, or 128 + signal when it was killed.
    @discardableResult
    public static func wait(_ pid: pid_t) -> Int32 {
        var status: Int32 = 0
        while waitpid(pid, &status, 0) == -1 {
            if errno != EINTR { return -1 }
        }
        let signal = status & 0x7f
        return signal == 0 ? (status >> 8) & 0xff : 128 + signal
    }
}
