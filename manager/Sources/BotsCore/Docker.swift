import Foundation

/// `docker compose -f <compose_file>` up / down / ps.
enum Docker {
    struct Container: Decodable {
        let name: String?
        let service: String?
        let state: String?
        enum CodingKeys: String, CodingKey { case name = "Name", service = "Service", state = "State" }
    }

    static func compose(_ s: ServiceConfig, _ args: [String], timeout: TimeInterval) throws -> ShellResult {
        guard let file = s.composePath else { throw ActionError("falta \"compose_file\"") }
        guard let docker = Shell.which("docker") else { throw ActionError("docker não encontrado") }
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = Shell.loginPath
        let cwd = s.cwdPath ?? (file as NSString).deletingLastPathComponent
        return Shell.run(docker, ["compose", "-f", file] + args, cwd: cwd, env: env, timeout: timeout)
    }

    /// `docker compose ps --format json` prints a JSON array (old) or one object per line (new).
    static func parsePS(_ text: String) -> [Container] {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }
        let decoder = JSONDecoder()
        if trimmed.hasPrefix("["), let list = try? decoder.decode([Container].self, from: Data(trimmed.utf8)) {
            return list
        }
        return trimmed.split(separator: "\n").compactMap { try? decoder.decode(Container.self, from: Data($0.utf8)) }
    }

    static func daemonDown(_ r: ShellResult) -> Bool {
        let t = r.stderr + r.stdout
        return t.contains("Cannot connect to the Docker daemon") || t.contains("docker daemon is not running")
            || t.contains("Is the docker daemon running") || t.contains("failed to connect to the docker API")
            || t.contains("docker.sock")
    }

    static func status(_ s: ServiceConfig) -> ServiceStatus {
        let r: ShellResult
        do { r = try compose(s, ["ps", "--all", "--format", "json"], timeout: 15) } catch {
            return .problem(error.localizedDescription)
        }
        if !r.ok {
            if daemonDown(r) {
                return ServiceStatus(state: .stopped, detail: "Docker fechado", canStop: false, canStart: true)
            }
            return .problem(r.message)
        }
        let list = parsePS(r.stdout)
        let running = list.filter { $0.state == "running" }.count
        if list.isEmpty {
            return ServiceStatus(state: .stopped, detail: "parado", canStop: false, canStart: true)
        }
        let word = list.count == 1 ? "container" : "containers"
        if running == list.count {
            return ServiceStatus(state: .running, detail: "rodando · \(running) \(word)", canStop: true, canStart: false)
        }
        if running == 0 {
            let exited = list.contains { $0.state == "exited" || $0.state == "dead" }
            return ServiceStatus(state: exited ? .failed : .stopped, detail: exited ? "containers parados" : "parado",
                                 canStop: true, canStart: true)
        }
        return ServiceStatus(state: .warning, detail: "\(running) de \(list.count) rodando", canStop: true, canStart: true)
    }

    static func run(_ s: ServiceConfig, _ args: [String], what: String) throws {
        let r = try compose(s, args, timeout: 180)
        if !r.ok {
            if daemonDown(r) { throw ActionError("Docker não está aberto. Abra o Docker Desktop.") }
            throw ActionError("docker compose \(what): \(r.message)")
        }
    }

    static func start(_ s: ServiceConfig) throws { try run(s, ["up", "-d"], what: "up") }
    static func stop(_ s: ServiceConfig) throws { try run(s, ["down"], what: "down") }
    static func restart(_ s: ServiceConfig) throws { try run(s, ["up", "-d", "--force-recreate"], what: "restart") }
}
