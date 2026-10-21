import Foundation

public enum ServiceState: String, Sendable, Codable {
    case running        // verde
    case warning        // amarelo: rodando, mas o site não responde / reiniciando
    case scheduled      // azul: launchd carregado, espera a hora
    case paused         // laranja: plist existe, mas não está carregado
    case stopped        // cinza
    case failed         // vermelho
    case notInstalled   // cinza claro
    case unknown

    public var isActive: Bool { self == .running || self == .warning }
}

public struct ServiceStatus: Sendable, Equatable {
    public var state: ServiceState
    /// Short text for the row, e.g. "rodando · pid 123".
    public var detail: String
    public var pid: Int32?
    /// nil when the service has no url.
    public var siteUp: Bool?
    /// True when something can be stopped / paused.
    public var canStop: Bool
    /// True when "start" makes sense (not already running).
    public var canStart: Bool

    public init(state: ServiceState, detail: String, pid: Int32? = nil, siteUp: Bool? = nil, canStop: Bool, canStart: Bool) {
        self.state = state
        self.detail = detail
        self.pid = pid
        self.siteUp = siteUp
        self.canStop = canStop
        self.canStart = canStart
    }

    public static func problem(_ text: String) -> ServiceStatus {
        ServiceStatus(state: .failed, detail: text, canStop: false, canStart: false)
    }
}

public struct ActionError: LocalizedError, Sendable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

public enum ServiceAction: String, Sendable, CaseIterable {
    case start, stop, restart
}
