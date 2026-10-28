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
        try {
            return rest.post().uri("/api/grade")
                    .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                    .body(Map.of("question_id", questionId, "answer", answer))
                    .retrieve().body(GradeResultDto.class);
        } catch (Exception e) {
            throw new AiServiceUnavailableException(e);
        }
    }

    public AskResultDto ask(String query) {
        try {
            return rest.post().uri("/api/ask")
                    .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                    .body(Map.of("query", query))
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
}
