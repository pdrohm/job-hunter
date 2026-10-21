import BotsCore
import Foundation

// bots-manager [--config FILE] status | start <id> | stop <id> | restart <id> | log <id>

var args = Array(CommandLine.arguments.dropFirst())
var configPath = ConfigLoader.defaultPath
if let i = args.firstIndex(of: "--config"), i + 1 < args.count {
    configPath = Paths.expand(args[i + 1])
    args.removeSubrange(i...(i + 1))
}

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(1)
}

let usage = """
Uso: bots-manager [--config ARQUIVO] <comando>
  status              mostra todos os serviços
  start <id|grupo>    inicia
  stop <id|grupo>     para / pausa
  restart <id|grupo>  reinicia
  log <id>            últimas 200 linhas do log
Config: \(configPath)
"""

guard let cmd = args.first else { print(usage); exit(0) }

let services: [ServiceConfig]
do { services = try ConfigLoader.load(path: configPath) } catch { fail(error.localizedDescription) }

func pick(_ name: String?, in services: [ServiceConfig], file: String) -> [ServiceConfig] {
    guard let name else { fail("falta o id. Veja: bots-manager status") }
    let found = services.filter { $0.id == name || $0.group == name }
    if found.isEmpty { fail("não achei \"\(name)\" em \(file)") }
    return found
}

final class Results: @unchecked Sendable {
    private let lock = NSLock()
    private var map = [String: ServiceStatus]()
    subscript(id: String) -> ServiceStatus? {
        get { lock.lock(); defer { lock.unlock() }; return map[id] }
        set { lock.lock(); map[id] = newValue; lock.unlock() }
    }
}

switch cmd {
case "status":
    let groups = ConfigLoader.groups(services)
    // Check all services at the same time.
    let results = Results()
    let list = services
    DispatchQueue.concurrentPerform(iterations: list.count) { i in
        results[list[i].id] = ServiceController.status(list[i])
    }
    let width = services.map(\.id.count).max() ?? 10
    for g in groups {
        print("[\(g.name)]")
        for s in g.services {
            let st = results[s.id]!
            let id = s.id.padding(toLength: width, withPad: " ", startingAt: 0)
            let state = st.state.rawValue.padding(toLength: 12, withPad: " ", startingAt: 0)
            print("  \(id)  \(state)  \(st.detail)")
        }
    }
case "start", "stop", "restart":
    let action = ServiceAction(rawValue: cmd)!
    var failed = false
    for s in pick(args.dropFirst().first, in: services, file: configPath) {
        do {
            try ServiceController.perform(action, s)
            print("\(s.id): ok · \(ServiceController.status(s).detail)")
        } catch {
            failed = true
            print("\(s.id): erro · \(error.localizedDescription)")
        }
    }
    exit(failed ? 1 : 0)
case "log":
    let s = pick(args.dropFirst().first, in: services, file: configPath)[0]
    if s.kind == .docker { print(ServiceController.dockerLogs(s)); break }
    guard let path = ServiceController.logPath(s) else { fail("sem log") }
    print(LogFile.tail(path) ?? "(log vazio: \(path))")
default:
    print(usage)
    exit(2)
}
