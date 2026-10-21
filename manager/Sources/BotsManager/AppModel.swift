import AppKit
import BotsCore
import Observation
import ServiceManagement

@MainActor
@Observable
final class AppModel {
    let configPath = ConfigLoader.defaultPath

    private(set) var services: [ServiceConfig] = []
    private(set) var groups: [ServiceGroup] = []
    private(set) var configError: String?
    private(set) var statuses: [String: ServiceStatus] = [:]
    private(set) var busy: Set<String> = []
    var errors: [String: String] = [:]
    private(set) var loaded = false

    /// The service whose log is shown, or nil for the list.
    var logService: ServiceConfig?

    private(set) var launchAtLogin = false
    var loginMessage: String?

    private var configDate: Date?
    private var lastRefresh = Date.distantPast
    private var refreshing = false
    private var isOpen = false

    init() {
        updateLoginState()
        Task { await loop() }
    }

    // MARK: Summary

    var failedCount: Int { statuses.values.filter { $0.state == .failed }.count }
    var runningCount: Int { statuses.values.filter { $0.state.isActive }.count }

    var menuIcon: String {
        failedCount > 0 || configError != nil
            ? "square.stack.3d.up.trianglebadge.exclamationmark.fill"
            : "square.stack.3d.up"
    }

    // MARK: Refresh

    /// Every 3 s while the window is open, every 60 s when closed (only for the menu bar badge).
    private func loop() async {
        while true {
            let interval: TimeInterval = isOpen ? 3 : 60
            if Date().timeIntervalSince(lastRefresh) >= interval { await refresh() }
            try? await Task.sleep(for: .seconds(1))
        }
    }

    func windowOpened() {
        isOpen = true
        updateLoginState()
        Task { await refresh() }
    }

    func windowClosed() {
        isOpen = false
        logService = nil
    }

    func refresh(forceConfig: Bool = false) async {
        guard !refreshing else { return }
        refreshing = true
        defer { refreshing = false; lastRefresh = Date() }
        reloadConfigIfChanged(force: forceConfig)
        let list = services
        // Forget services that left the config.
        let ids = Set(list.map(\.id))
        statuses = statuses.filter { ids.contains($0.key) }
        await withTaskGroup(of: (String, ServiceStatus).self) { group in
            for s in list {
                group.addTask { (s.id, await offMain { ServiceController.status(s) }) }
            }
            // Show each result as soon as it comes (a slow docker check does not hold the others).
            for await (id, st) in group where !busy.contains(id) { statuses[id] = st }
        }
        loaded = true
    }

    private func reloadConfigIfChanged(force: Bool) {
        let attrs = try? FileManager.default.attributesOfItem(atPath: configPath)
        let date = attrs?[.modificationDate] as? Date
        guard force || date != configDate || date == nil else { return }
        configDate = date
        guard date != nil else {
            services = []
            groups = []
            configError = nil
            return
        }
        do {
            services = try ConfigLoader.load(path: configPath)
            groups = ConfigLoader.groups(services)
            configError = nil
        } catch {
            configError = error.localizedDescription  // keep the last good list
        }
    }

    func reload() {
        Task { await refresh(forceConfig: true) }
    }

    // MARK: Actions

    func perform(_ action: ServiceAction, _ s: ServiceConfig) {
        guard !busy.contains(s.id) else { return }
        busy.insert(s.id)
        errors[s.id] = nil
        Task {
            let error: String? = await offMain {
                do { try ServiceController.perform(action, s); return nil } catch { return error.localizedDescription }
            }
            // A site needs a moment to answer after the process starts.
            if error == nil, action != .stop, s.checkURL != nil { try? await Task.sleep(for: .seconds(1.5)) }
            let st = await offMain { ServiceController.status(s) }
            statuses[s.id] = st
            errors[s.id] = error
            busy.remove(s.id)
        }
    }

    func startAll(_ g: ServiceGroup) {
        for s in g.services where statuses[s.id]?.canStart ?? true {
            // "Iniciar todos" runs services, it does not run scheduled jobs early.
            if statuses[s.id]?.state == .scheduled { continue }
            perform(.start, s)
        }
    }

    func stopAll(_ g: ServiceGroup) {
        for s in g.services where statuses[s.id]?.canStop ?? false { perform(.stop, s) }
    }

    func openSite(_ s: ServiceConfig) {
        if let url = s.siteURL ?? s.checkURL { NSWorkspace.shared.open(url) }
    }

    func openFolder(_ s: ServiceConfig) {
        guard let path = ServiceController.folder(s) else { errors[s.id] = "sem pasta"; return }
        guard FileManager.default.fileExists(atPath: path) else { errors[s.id] = "pasta não existe: \(path)"; return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path, isDirectory: true))
    }

    func openInConsole(_ path: String) {
        let url = URL(fileURLWithPath: path)
        guard let console = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Console") else {
            NSWorkspace.shared.open(url)
            return
        }
        NSWorkspace.shared.open([url], withApplicationAt: console, configuration: NSWorkspace.OpenConfiguration())
    }

    func editConfig() {
        if !FileManager.default.fileExists(atPath: configPath) {
            Paths.ensureDir((configPath as NSString).deletingLastPathComponent)
            try? ConfigLoader.template.write(toFile: configPath, atomically: true, encoding: .utf8)
        }
        let url = URL(fileURLWithPath: configPath)
        // Open as text (the default app for .json may be a viewer).
        if let editor = NSWorkspace.shared.urlForApplication(toOpen: url) {
            NSWorkspace.shared.open([url], withApplicationAt: editor, configuration: NSWorkspace.OpenConfiguration())
        } else if let textEdit = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.TextEdit") {
            NSWorkspace.shared.open([url], withApplicationAt: textEdit, configuration: NSWorkspace.OpenConfiguration())
        }
    }

    // MARK: Open at login

    func updateLoginState() {
        let status = SMAppService.mainApp.status
        launchAtLogin = status == .enabled
        if status == .requiresApproval {
            loginMessage = "Aprove em Ajustes › Geral › Itens de Início."
        }
    }

    func setLaunchAtLogin(_ on: Bool) {
        loginMessage = nil
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            loginMessage = "Não deu: \(error.localizedDescription)"
        }
        updateLoginState()
        if on && SMAppService.mainApp.status == .requiresApproval {
            SMAppService.openSystemSettingsLoginItems()
        }
    }
}
