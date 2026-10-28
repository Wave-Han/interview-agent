package com.wavehan.agentweb.service;

import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import com.wavehan.agentweb.dto.AskResultDto;
import com.wavehan.agentweb.dto.GradeResultDto;
import com.wavehan.agentweb.dto.QuestionDto;
import com.wavehan.agentweb.dto.StatsDto;

/**
 * Thin HTTP client over the Python FastAPI AI service (four endpoints).
 * Each method maps one endpoint onto its DTO; any failure (service down,
 * timeout, decode error) is translated into {@link AiServiceUnavailableException}
 * so controllers can render a friendly page instead of a stack trace.
 */
@Service
public class AiClientService {

    private final RestClient rest;

    @Autowired
    public AiClientService(@Value("${python-api.base-url}") String baseUrl) {
        this(RestClient.builder().baseUrl(baseUrl).build());
    }

    /** Direct-injection constructor so unit tests can pass a mocked RestClient. */
    public AiClientService(RestClient restClient) {
        this.rest = restClient;
    }

    /**
     * Pick a question for a topic. Convention: callers (the web controller)
     * always pass a non-null {@code excludeIds} — "" when nothing is excluded
     * — so this method never has to branch on null.
     */
    public QuestionDto fetchQuestion(String topic, boolean wrongOnly, String excludeIds) {
        try {
            return rest.get()
                    .uri("/api/question?topic={topic}&wrong_only={wrongOnly}&exclude_ids={excludeIds}",
                            topic, wrongOnly, excludeIds)
                    .retrieve()
                    .body(QuestionDto.class);
        } catch (Exception e) {
            throw new AiServiceUnavailableException(e);
        }
    }

    public GradeResultDto grade(long questionId, String answer) {
        // Null args must fail fast as IllegalArgumentException, not be
        // mistranslated into "service down" by the catch-all below — hence
        // validation and body building happen before the try block.
        requireNonNull("answer", answer);
        Map<String, Object> body = Map.of("question_id", questionId, "answer", answer);
        try {
            return rest.post().uri("/api/grade")
                    .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                    .body(body)
                    .retrieve().body(GradeResultDto.class);
        } catch (Exception e) {
            throw new AiServiceUnavailableException(e);
        }
    }

    public AskResultDto ask(String query) {
        requireNonNull("query", query);
        Map<String, Object> body = Map.of("query", query);
        try {
            return rest.post().uri("/api/ask")
                    .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                    .body(body)
                    .retrieve().body(AskResultDto.class);
        } catch (Exception e) {
            throw new AiServiceUnavailableException(e);
        }
    }

    public StatsDto stats(String topic) {
        try {
            return rest.get().uri("/api/stats?topic={topic}", topic)
                    .retrieve().body(StatsDto.class);
        } catch (Exception e) {
            throw new AiServiceUnavailableException(e);
        }
    }

    private static void requireNonNull(String name, String value) {
        if (value == null) {
            throw new IllegalArgumentException(name + " must not be null");
        }
    }
}
