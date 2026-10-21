import Foundation

/// What `launchctl print gui/<uid>/<label>` says about a loaded agent.
public struct LaunchdInfo: Equatable, Sendable {
    public var state: String?
    public var pid: Int32?
    /// nil when the job never exited.
    public var lastExitCode: Int32?
    /// e.g. "Killed: 9"
    public var lastSignal: String?
    public var runs: Int?

    /// Reads only the top-level keys (one tab of indent); nested blocks repeat "state".
    public static func parse(_ text: String) -> LaunchdInfo {
        var info = LaunchdInfo()
        for raw in text.split(separator: "\n", omittingEmptySubsequences: true) {
            guard raw.hasPrefix("\t"), !raw.hasPrefix("\t\t") else { continue }
            let line = raw.dropFirst()
            guard let eq = line.range(of: " = ") else { continue }
            let key = line[..<eq.lowerBound]
            let value = String(line[eq.upperBound...]).trimmingCharacters(in: .whitespaces)
            switch key {
            case "state": info.state = value
            case "pid": info.pid = Int32(value)
            case "last exit code": info.lastExitCode = Int32(value)  // "(never exited)" -> nil
            case "last terminating signal": info.lastSignal = value
            case "runs": info.runs = Int(value)
            default: break
            }
        }
        return info
    }
}

/// What the plist file says about when the agent runs.
public struct LaunchdPlist: Sendable {
    public var keepAlive = false
    public var runAtLoad = false
    /// Short text, e.g. "08:00", "a cada 2 h".
    public var schedule: String?
    public var workingDirectory: String?
    public var logPath: String?

    public init() {}

    public static func read(path: String) -> LaunchdPlist? {
        guard let data = FileManager.default.contents(atPath: path),
              let obj = try? PropertyListSerialization.propertyList(from: data, format: nil),
              let dict = obj as? [String: Any] else { return nil }
        return from(dict)
    }

    public static func from(_ dict: [String: Any]) -> LaunchdPlist {
        var p = LaunchdPlist()
        if let b = dict["KeepAlive"] as? Bool { p.keepAlive = b } else if dict["KeepAlive"] is [String: Any] { p.keepAlive = true }
        p.runAtLoad = dict["RunAtLoad"] as? Bool ?? false
        p.workingDirectory = dict["WorkingDirectory"] as? String
        p.logPath = (dict["StandardOutPath"] as? String) ?? (dict["StandardErrorPath"] as? String)
        if let seconds = (dict["StartInterval"] as? NSNumber)?.intValue, seconds > 0 {
            p.schedule = everyText(seconds)
        } else if let cal = dict["StartCalendarInterval"] as? [String: Any] {
            p.schedule = calendarText([cal])
        } else if let cals = dict["StartCalendarInterval"] as? [[String: Any]], !cals.isEmpty {
            p.schedule = calendarText(cals)
        }
        return p
    }

    static func everyText(_ s: Int) -> String {
        if s % 3600 == 0 { return "a cada \(s / 3600) h" }
        if s % 60 == 0 { return "a cada \(s / 60) min" }
        return "a cada \(s) s"
    }

    static let weekdays = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

    static func calendarText(_ items: [[String: Any]]) -> String {
        let parts = items.prefix(3).map { item -> String in
            let h = (item["Hour"] as? NSNumber)?.intValue
            let m = (item["Minute"] as? NSNumber)?.intValue ?? 0
            var text: String
            if let h { text = String(format: "%02d:%02d", h, m) } else { text = String(format: "min %02d de cada hora", m) }
            if let d = (item["Weekday"] as? NSNumber)?.intValue, (0...7).contains(d) { text = "\(weekdays[d]) " + text }
            if let day = (item["Day"] as? NSNumber)?.intValue { text = "dia \(day) " + text }
            return text
        }
        return parts.joined(separator: ", ") + (items.count > 3 ? "…" : "")
    }
}

enum Launchd {
    static let launchctl = "/bin/launchctl"
    static var domain: String { "gui/\(getuid())" }

    static func target(_ label: String) -> String { "\(domain)/\(label)" }

    static func print(_ label: String) -> ShellResult {
        Shell.run(launchctl, ["print", target(label)], timeout: 10)
    }

    static func status(_ s: ServiceConfig) -> ServiceStatus {
        guard let label = s.label, let plistPath = s.plistPath else { return .problem("falta \"label\"") }
        let plistExists = FileManager.default.fileExists(atPath: plistPath)
        let plist = LaunchdPlist.read(path: plistPath)
        let r = print(label)
        guard r.ok else {
            if plistExists {
                return ServiceStatus(state: .paused, detail: "pausado", canStop: false, canStart: true)
            }
            return ServiceStatus(state: .notInstalled, detail: "não instalado", canStop: false, canStart: false)
        }
        let info = LaunchdInfo.parse(r.stdout)
        // "running", or "xpcproxy" / "spawn scheduled" while it starts.
        if info.state == "running" || info.pid != nil {
            let detail = info.pid.map { "rodando · pid \($0)" } ?? "rodando"
            return ServiceStatus(state: .running, detail: detail, pid: info.pid, canStop: true, canStart: false)
        }
        let schedule = plist?.schedule
        let badSignal = info.lastSignal.flatMap { $0.hasPrefix("Terminated") ? nil : $0 }
        if let code = info.lastExitCode, code != 0 {
            let detail = schedule.map { "erro \(code) na última vez · \($0)" } ?? "parou com erro \(code)"
            return ServiceStatus(state: .failed, detail: detail, canStop: true, canStart: true)
        }
        if let badSignal {
            let detail = schedule.map { "caiu (\(badSignal)) · \($0)" } ?? "caiu (\(badSignal))"
            return ServiceStatus(state: .failed, detail: detail, canStop: true, canStart: true)
        }
        if let schedule {
            let text = schedule.hasPrefix("a cada") ? "agendado · \(schedule)" : "agendado \(schedule)"
            return ServiceStatus(state: .scheduled, detail: text, canStop: true, canStart: true)
        }
        if plist?.keepAlive == true {
            return ServiceStatus(state: .warning, detail: "reiniciando…", canStop: true, canStart: true)
        }
        return ServiceStatus(state: .stopped, detail: "parado (carregado)", canStop: true, canStart: true)
    }

    static func start(_ s: ServiceConfig) throws {
        guard let label = s.label, let plistPath = s.plistPath else { throw ActionError("falta \"label\"") }
        if !print(label).ok {
            guard FileManager.default.fileExists(atPath: plistPath) else {
                throw ActionError("não instalado: \((plistPath as NSString).lastPathComponent) não existe")
            }
            var r = Shell.run(launchctl, ["bootstrap", domain, plistPath])
            if !r.ok {
                // A disabled agent does not load; "Iniciar" is a clear request, so enable it.
                Shell.run(launchctl, ["enable", target(label)])
                r = Shell.run(launchctl, ["bootstrap", domain, plistPath])
            }
            guard r.ok else { throw ActionError("launchctl bootstrap: \(r.message)") }
            // RunAtLoad agents start by themselves when loaded.
            if LaunchdPlist.read(path: plistPath)?.runAtLoad == true { return }
        }
        let r = Shell.run(launchctl, ["kickstart", target(label)])
        guard r.ok else { throw ActionError("launchctl kickstart: \(r.message)") }
    }

    static func stop(_ s: ServiceConfig) throws {
        guard let label = s.label else { throw ActionError("falta \"label\"") }
        guard print(label).ok else { return }  // already unloaded
        let r = Shell.run(launchctl, ["bootout", target(label)], timeout: 40)
        if !r.ok && print(label).ok { throw ActionError("launchctl bootout: \(r.message)") }
    }

    static func restart(_ s: ServiceConfig) throws {
        guard let label = s.label else { throw ActionError("falta \"label\"") }
        guard print(label).ok else { return try start(s) }
        let r = Shell.run(launchctl, ["kickstart", "-k", target(label)], timeout: 40)
        guard r.ok else { throw ActionError("launchctl kickstart -k: \(r.message)") }
    }
}
