package com.wavehan.agentweb.service;

import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClient;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.wavehan.agentweb.dto.AskResultDto;
import com.wavehan.agentweb.dto.GradeResultDto;
import com.wavehan.agentweb.dto.QuestionDto;
import com.wavehan.agentweb.dto.StatsDto;

/**
 * Thin HTTP client over the Python FastAPI AI service (four endpoints).
 * Each method maps one endpoint onto its DTO; any failure is translated
 * into {@link AiServiceUnavailableException} so controllers can render a
 * friendly page instead of a stack trace. Non-2xx responses are special:
 * Python already wrote a structured Chinese message into the body (502 LLM
 * failure, 404 unknown question), so their text is surfaced as-is while
 * transport-level failures keep the "service not started" wording.
 */
@Service
public class AiClientService {

    private static final ObjectMapper JSON = new ObjectMapper();

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
        } catch (HttpStatusCodeException e) {
            // Python returned a structured error (e.g. 502 LLM failure with
            // Chinese detail). Surface its body/message instead of masking
            // as "service unavailable".
            throw new AiServiceUnavailableException(extractMessage(e));
        } catch (Exception e) {
            // Transport-level failure (connection refused, timeout, decode).
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
        } catch (HttpStatusCodeException e) {
            // Python returned a structured error (e.g. 502 LLM failure with
            // Chinese detail). Surface its body/message instead of masking
            // as "service unavailable".
            throw new AiServiceUnavailableException(extractMessage(e));
        } catch (Exception e) {
            // Transport-level failure (connection refused, timeout, decode).
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
        } catch (HttpStatusCodeException e) {
            // Python returned a structured error (e.g. 502 LLM failure with
            // Chinese detail). Surface its body/message instead of masking
            // as "service unavailable".
            throw new AiServiceUnavailableException(extractMessage(e));
        } catch (Exception e) {
            // Transport-level failure (connection refused, timeout, decode).
            throw new AiServiceUnavailableException(e);
        }
    }

    public StatsDto stats(String topic) {
        try {
            return rest.get().uri("/api/stats?topic={topic}", topic)
                    .retrieve().body(StatsDto.class);
        } catch (HttpStatusCodeException e) {
            // Python returned a structured error (e.g. 502 LLM failure with
            // Chinese detail). Surface its body/message instead of masking
            // as "service unavailable".
            throw new AiServiceUnavailableException(extractMessage(e));
        } catch (Exception e) {
            // Transport-level failure (connection refused, timeout, decode).
            throw new AiServiceUnavailableException(e);
        }
    }

    private static void requireNonNull(String name, String value) {
        if (value == null) {
            throw new IllegalArgumentException(name + " must not be null");
        }
    }

    /**
     * Recover the user-facing message from a Python error response: FastAPI
     * writes {@code {"detail": ...}}; the "error" key is accepted as a
     * fallback. Any non-JSON or empty body degrades to a status-code-only
     * Chinese message.
     */
    private static String extractMessage(HttpStatusCodeException e) {
        try {
            JsonNode root = JSON.readTree(e.getResponseBodyAsString());
            String detail = root.path("detail").asText(null);
            if (detail == null || detail.isBlank()) {
                detail = root.path("error").asText(null);
            }
            if (detail != null && !detail.isBlank()) {
                return detail;
            }
        } catch (Exception ignored) {
            // Unparseable body falls through to the generic message below.
        }
        return "AI 服务错误(" + e.getStatusCode().value() + ")";
    }
}
