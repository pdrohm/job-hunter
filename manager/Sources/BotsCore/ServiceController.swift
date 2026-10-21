import Foundation

/// The one entry point the app and the CLI use. All methods block: call them off the main thread.
public enum ServiceController {
    /// Status of the process plus the site health (when `url` is set).
    public static func status(_ s: ServiceConfig) -> ServiceStatus {
        if let p = s.problem { return .problem(p) }
        var st: ServiceStatus
        switch s.kind {
        case .launchd: st = Launchd.status(s)
        case .command: st = CommandRunner.status(s)
        case .docker: st = Docker.status(s)
        }
        guard let url = s.checkURL else { return st }
        let up = Health.check(url)
        st.siteUp = up
        switch st.state {
        case .running:
            if !up { st.state = .warning; st.detail += " · site não responde" }
        case .stopped, .paused, .scheduled, .failed, .notInstalled, .unknown:
            if up {
                // The site answers but we did not start it (e.g. run from a Terminal).
                if s.kind == .command && st.state != .failed {
                    st.state = .running
                    st.detail = "rodando fora do app"
                    st.canStart = false
                }
            }
        case .warning:
            break
        }
        return st
    }

    public static func perform(_ action: ServiceAction, _ s: ServiceConfig) throws {
        if let p = s.problem { throw ActionError(p) }
        switch (s.kind, action) {
        case (.launchd, .start): try Launchd.start(s)
        case (.launchd, .stop): try Launchd.stop(s)
        case (.launchd, .restart): try Launchd.restart(s)
        case (.command, .start): try CommandRunner.start(s)
        case (.command, .stop):
            if CommandRunner.livePID(s) == nil, s.stopCommand == nil, let url = s.checkURL, Health.check(url) {
                throw ActionError("não foi iniciado aqui: pare onde ele foi aberto")
            }
            try CommandRunner.stop(s)
        case (.command, .restart):
            try CommandRunner.stop(s)
            try CommandRunner.start(s)
        case (.docker, .start): try Docker.start(s)
        case (.docker, .stop): try Docker.stop(s)
        case (.docker, .restart): try Docker.restart(s)
        }
    }

    /// The log file to show for a service (config `log`, the launchd plist, or our own log).
    public static func logPath(_ s: ServiceConfig) -> String? {
        if let log = s.log { return Paths.expand(log) }
        switch s.kind {
        case .command: return CommandRunner.defaultLog(s)
        case .launchd: return s.plistPath.flatMap { LaunchdPlist.read(path: $0)?.logPath }
        case .docker: return nil
        }
    }

    /// The folder to open: `cwd`, the agent's WorkingDirectory, or the log's folder.
    public static func folder(_ s: ServiceConfig) -> String? {
        if let cwd = s.cwdPath { return cwd }
        if s.kind == .launchd, let wd = s.plistPath.flatMap({ LaunchdPlist.read(path: $0)?.workingDirectory }) { return wd }
        if let compose = s.composePath { return (compose as NSString).deletingLastPathComponent }
        return logPath(s).map { ($0 as NSString).deletingLastPathComponent }
    }

    /// For docker services the log is `docker compose logs --tail`.
    public static func dockerLogs(_ s: ServiceConfig, lines: Int = 200) -> String {
        guard s.kind == .docker else { return "" }
        guard let r = try? Docker.compose(s, ["logs", "--no-color", "--tail", "\(lines)"], timeout: 15) else { return "" }
        return r.ok ? r.stdout + r.stderr : r.message
    }
}

public enum Health {
    /// GET with a short timeout. 2xx / 3xx = up.
    public static func check(_ url: URL, timeout: TimeInterval = 2) -> Bool {
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        req.httpMethod = "GET"
        let result = LockedData()
        let sem = DispatchSemaphore(value: 0)
        let task = session.dataTask(with: req) { _, resp, _ in
            if let http = resp as? HTTPURLResponse, (200..<400).contains(http.statusCode) {
                result.set(Data([1]))
            }
            sem.signal()
        }
        task.resume()
        if sem.wait(timeout: .now() + timeout + 1) == .timedOut { task.cancel() }
        return result.get() == Data([1])
    }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 2
        c.timeoutIntervalForResource = 3
        c.waitsForConnectivity = false
        c.connectionProxyDictionary = [:]  // local sites: never go through a proxy
        return URLSession(configuration: c, delegate: NoRedirect(), delegateQueue: nil)
    }()

    /// A redirect (3xx) already means "up"; do not follow it.
    final class NoRedirect: NSObject, URLSessionTaskDelegate, Sendable {
        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest) async -> URLRequest? { nil }
    }
}

public enum LogFile {
    /// The last `lines` lines of a text file (reads at most the last 256 KB).
    public static func tail(_ path: String, lines: Int = 200) -> String? {
        guard let h = FileHandle(forReadingAtPath: path) else { return nil }
        defer { try? h.close() }
        let size = (try? h.seekToEnd()) ?? 0
        let chunk: UInt64 = 256 * 1024
        let start = size > chunk ? size - chunk : 0
        try? h.seek(toOffset: start)
        let data = (try? h.readToEnd()) ?? Data()
        var text = String(decoding: data, as: UTF8.self)
        if start > 0, let nl = text.firstIndex(of: "\n") { text = String(text[text.index(after: nl)...]) }
        let all = text.split(separator: "\n", omittingEmptySubsequences: false)
        return all.suffix(lines).joined(separator: "\n")
    }
}
