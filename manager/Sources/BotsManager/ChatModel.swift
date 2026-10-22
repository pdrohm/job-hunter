import BotsCore
import Foundation
import Observation

struct ChatMessage: Codable, Identifiable, Equatable {
    enum Role: String, Codable { case user, assistant, tool, error }
    var id = UUID()
    let role: Role
    var text: String
}

/// The chat with Claude Code. Each message is one `claude -p` run that resumes the same session,
/// so Claude keeps the context. Saved in `~/.bots-manager/chat.json`.
@MainActor
@Observable
final class ChatModel {
    private(set) var messages: [ChatMessage] = []
    private(set) var running = false
    var draft = ""

    private var session: String?
    private var run: ClaudeRun?
    private let file = Paths.stateDir + "/chat.json"
    private let maxSaved = 300

    private struct Saved: Codable {
        var session: String?
        var messages: [ChatMessage]
    }

    /// Claude works here; the folders of all services are added with --add-dir.
    var workDir: String { Paths.stateDir + "/chat" }

    init() {
        if let data = try? Data(contentsOf: URL(fileURLWithPath: file)),
           let saved = try? JSONDecoder().decode(Saved.self, from: data) {
            session = saved.session
            messages = saved.messages
        }
    }

    func send(services: [ServiceConfig], configPath: String) {
        let prompt = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !running else { return }
        draft = ""
        messages.append(ChatMessage(role: .user, text: prompt))
        running = true
        save()

        let r = ClaudeRun()
        run = r
        let dirs = Array(Set(services.compactMap(\.cwdPath))).sorted()
            .filter { FileManager.default.fileExists(atPath: $0) }
        let stream = r.start(prompt: prompt, session: session, cwd: workDir, addDirs: dirs,
                             systemPrompt: Self.systemPrompt(services: services, configPath: configPath))
        Task {
            for await event in stream {
                switch event {
                case .session(let id):
                    session = id
                case .text(let t):
                    messages.append(ChatMessage(role: .assistant, text: t))
                case .tool(let t):
                    messages.append(ChatMessage(role: .tool, text: t))
                case .done(let ok, let text):
                    if !ok { messages.append(ChatMessage(role: .error, text: text)) }
                }
            }
            running = false
            run = nil
            save()
        }
    }

    func stop() { run?.stop() }

    func newChat() {
        guard !running else { return }
        session = nil
        messages = []
        save()
    }

    private func save() {
        Paths.ensureDir(Paths.stateDir)
        let saved = Saved(session: session, messages: Array(messages.suffix(maxSaved)))
        if let data = try? JSONEncoder().encode(saved) {
            try? data.write(to: URL(fileURLWithPath: file), options: .atomic)
        }
    }

    static func systemPrompt(services: [ServiceConfig], configPath: String) -> String {
        let cli = Bundle.main.executableURL?.deletingLastPathComponent().appendingPathComponent("bots-manager").path
        let cliLine = cli.flatMap { FileManager.default.isExecutableFile(atPath: $0) ? $0 : nil }
            .map { "Control services with the CLI: \"\($0)\" status | start <id> | stop <id> | restart <id> | log <id>." }
            ?? "Control services with launchctl, docker compose or the commands in the config."
        let list = services.map { s in
            "- \(s.id) (\(s.kind.rawValue), \(s.name))" + (s.cwdPath.map { " in \($0)" } ?? "")
        }.joined(separator: "\n")
        return """
        You run inside Bots Manager, a macOS menu bar app that starts and stops the user's bots and projects.
        The user talks to you in a small chat window. Nobody can answer a tool permission prompt or an \
        AskUserQuestion here: when you need a decision, ask in your text reply and stop.
        Services config: \(configPath)
        \(cliLine)
        Services:
        \(list.isEmpty ? "(none yet)" : list)
        Keep replies short. Use the user's language.
        """
    }
}
