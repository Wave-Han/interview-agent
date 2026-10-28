package com.wavehan.agentweb;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Entry point of the Java web gateway. All AI logic lives in the Python
 * FastAPI service; this application is a UI/controller shell that proxies
 * to it via {@code AiClientService}.
 */
@SpringBootApplication
public class AgentWebApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentWebApplication.class, args);
    }
}
