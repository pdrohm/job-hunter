import Foundation

/// How a service is run.
public enum ServiceKind: String, Codable, Sendable {
    case launchd
    case command
    case docker
}

/// One entry of `services.json`.
public struct ServiceConfig: Codable, Sendable, Identifiable, Equatable {
    public var id: String
    public var name: String
    public var group: String
    public var kind: ServiceKind
    public var description: String?
    /// Site to open. Also used for the health check, unless `health_url` is set.
    public var url: String?
    public var healthURL: String?
    public var cwd: String?
    public var log: String?
    // launchd
    public var label: String?
    public var plist: String?
    // command
    public var command: String?
    public var env: [String: String]?
    public var stopCommand: String?
    // docker
    public var composeFile: String?

    enum CodingKeys: String, CodingKey {
        case id, name, group, kind, description, url, cwd, log, label, plist, command, env
        case healthURL = "health_url"
        case stopCommand = "stop_command"
        case composeFile = "compose_file"
    }

    public init(id: String, name: String, group: String, kind: ServiceKind) {
        self.id = id
        self.name = name
        self.group = group
        self.kind = kind
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        group = try c.decodeIfPresent(String.self, forKey: .group) ?? "Outros"
        kind = try c.decode(ServiceKind.self, forKey: .kind)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        healthURL = try c.decodeIfPresent(String.self, forKey: .healthURL)
        cwd = try c.decodeIfPresent(String.self, forKey: .cwd)
        log = try c.decodeIfPresent(String.self, forKey: .log)
        label = try c.decodeIfPresent(String.self, forKey: .label)
        plist = try c.decodeIfPresent(String.self, forKey: .plist)
        command = try c.decodeIfPresent(String.self, forKey: .command)
        env = try c.decodeIfPresent([String: String].self, forKey: .env)
        stopCommand = try c.decodeIfPresent(String.self, forKey: .stopCommand)
        composeFile = try c.decodeIfPresent(String.self, forKey: .composeFile)
    }

    // MARK: Resolved values

    public var cwdPath: String? { cwd.map { Paths.expand($0) } }

    public var plistPath: String? {
        if let plist { return Paths.expand(plist) }
        guard let label else { return nil }
        return Paths.expand("~/Library/LaunchAgents/\(label).plist")
    }

    public var composePath: String? {
        guard let composeFile else { return nil }
        return Paths.resolve(composeFile, relativeTo: cwdPath)
    }

    public var checkURL: URL? {
        guard let s = healthURL ?? url, !s.isEmpty else { return nil }
        return URL(string: s)
    }

    public var siteURL: URL? {
        guard let url, !url.isEmpty else { return nil }
        return URL(string: url)
    }

    /// Checks that the fields the kind needs are set. Returns a short message, or nil.
    public var problem: String? {
        switch kind {
        case .launchd: return label == nil ? "falta \"label\"" : nil
        case .command: return (command ?? "").isEmpty ? "falta \"command\"" : nil
        case .docker: return composeFile == nil ? "falta \"compose_file\"" : nil
        }
    }
}

public struct ServicesFile: Codable, Sendable {
    public var services: [ServiceConfig]
}

public struct ServiceGroup: Identifiable, Sendable, Equatable {
    public var id: String { name }
    public let name: String
    public let services: [ServiceConfig]
}

public enum ConfigError: LocalizedError {
    case unreadable(String)
    case invalid(String)
    case duplicateID(String)

    public var errorDescription: String? {
        switch self {
        case .unreadable(let m): return "Não deu para ler o arquivo: \(m)"
        case .invalid(let m): return "services.json inválido: \(m)"
        case .duplicateID(let id): return "id repetido em services.json: \(id)"
        }
    }
}

public enum ConfigLoader {
    /// `BOTS_MANAGER_CONFIG`, or `~/.bots-manager/services.json`.
    public static var defaultPath: String {
        if let p = ProcessInfo.processInfo.environment["BOTS_MANAGER_CONFIG"], !p.isEmpty {
            return Paths.expand(p)
        }
        return Paths.home + "/.bots-manager/services.json"
    }

    public static func load(path: String) throws -> [ServiceConfig] {
        let data: Data
        do {
            data = try Data(contentsOf: URL(fileURLWithPath: path))
        } catch {
            throw ConfigError.unreadable(error.localizedDescription)
        }
        return try parse(data)
    }

    public static func parse(_ data: Data) throws -> [ServiceConfig] {
        let services: [ServiceConfig]
        do {
            services = try JSONDecoder().decode(ServicesFile.self, from: data).services
        } catch let DecodingError.keyNotFound(key, ctx) {
            throw ConfigError.invalid("falta \"\(key.stringValue)\" em \(where_(ctx))")
        } catch let DecodingError.dataCorrupted(ctx) {
            throw ConfigError.invalid(ctx.debugDescription)
        } catch let DecodingError.typeMismatch(_, ctx) {
            throw ConfigError.invalid("tipo errado em \(where_(ctx))")
        } catch {
            throw ConfigError.invalid(error.localizedDescription)
        }
        var seen = Set<String>()
        for s in services {
            if !seen.insert(s.id).inserted { throw ConfigError.duplicateID(s.id) }
        }
        return services
    }

    private static func where_(_ ctx: DecodingError.Context) -> String {
        let path = ctx.codingPath.map { $0.intValue.map { "[\($0)]" } ?? $0.stringValue }.joined(separator: ".")
        return path.isEmpty ? "raiz" : path
    }

    /// Groups in the order they first appear in the file.
    public static func groups(_ services: [ServiceConfig]) -> [ServiceGroup] {
        var order: [String] = []
        var byName: [String: [ServiceConfig]] = [:]
        for s in services {
            if byName[s.group] == nil { order.append(s.group) }
            byName[s.group, default: []].append(s)
        }
        return order.map { ServiceGroup(name: $0, services: byName[$0] ?? []) }
    }

    public static let template = """
    {
      "services": [
        {
          "id": "my-site",
          "name": "Meu site",
          "group": "Projetos",
          "kind": "command",
          "command": "npm start",
          "cwd": "~/code/my-site",
          "url": "http://127.0.0.1:3000"
        }
      ]
    }

    """
}

public enum Paths {
    public static var home: String { NSHomeDirectory() }

    /// `BOTS_MANAGER_HOME`, or `~/.bots-manager`. Holds `run/` (pid files) and `logs/`.
    public static var stateDir: String {
        if let p = ProcessInfo.processInfo.environment["BOTS_MANAGER_HOME"], !p.isEmpty {
            return expand(p)
        }
        return home + "/.bots-manager"
    }

    public static var runDir: String { stateDir + "/run" }
    public static var logsDir: String { stateDir + "/logs" }

    /// Expands a leading `~` and `$VAR` / `${VAR}`.
    public static func expand(_ s: String, env: [String: String] = ProcessInfo.processInfo.environment) -> String {
        var out = s
        if out == "~" { out = home } else if out.hasPrefix("~/") { out = home + out.dropFirst() }
        guard out.contains("$") else { return out }
        var result = ""
        var i = out.startIndex
        while i < out.endIndex {
            let ch = out[i]
            guard ch == "$" else { result.append(ch); i = out.index(after: i); continue }
            var j = out.index(after: i)
            var name = ""
            if j < out.endIndex, out[j] == "{" {
                j = out.index(after: j)
                while j < out.endIndex, out[j] != "}" { name.append(out[j]); j = out.index(after: j) }
                if j < out.endIndex { j = out.index(after: j) }
            } else {
                while j < out.endIndex, out[j].isLetter || out[j].isNumber || out[j] == "_" {
                    name.append(out[j]); j = out.index(after: j)
                }
            }
            if name.isEmpty { result.append("$") } else { result += env[name] ?? "" }
            i = j
        }
        return result
    }

    public static func resolve(_ path: String, relativeTo base: String?) -> String {
        let p = expand(path)
        if p.hasPrefix("/") || base == nil { return p }
        return (base! as NSString).appendingPathComponent(p)
    }

    public static func ensureDir(_ path: String) {
        try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
    }
}
