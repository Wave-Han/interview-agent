package com.wavehan.agentweb.service;

/**
 * Thrown when the Python AI service cannot be reached (connection refused,
 * timeout, undecodable response). The message is user-facing Chinese text
 * shown as-is on the error page.
 */
public class AiServiceUnavailableException extends RuntimeException {

    public AiServiceUnavailableException() {
        super("AI 服务不可用,请先启动 Python 服务");
    }

    public AiServiceUnavailableException(Throwable cause) {
        super("AI 服务不可用,请先启动 Python 服务", cause);
    }
}
