package com.wavehan.agentweb.controller;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.ResponseBody;

import com.wavehan.agentweb.dto.GradeResultDto;
import com.wavehan.agentweb.service.AiClientService;
import com.wavehan.agentweb.service.AiServiceUnavailableException;

/**
 * Page routes plus the {@code /web/*} JSON aggregation endpoints called by
 * the page scripts. Page routes return Thymeleaf view names; every /web/*
 * endpoint delegates to {@link AiClientService} and degrades an unavailable
 * Python service to HTTP 200 {@code {"error": ...}} so pages can render a
 * friendly banner instead of a stack trace.
 */
@Controller
public class WebController {

    private final AiClientService aiClient;

    public WebController(AiClientService aiClient) {
        this.aiClient = aiClient;
    }

    @GetMapping("/")
    public String root() {
        return "redirect:/practice";
    }

    @GetMapping("/practice")
    public String practicePage() {
        return "practice";
    }

    @GetMapping("/stats")
    public String statsPage() {
        return "stats";
    }

    @GetMapping("/ask")
    public String askPage() {
        return "ask";
    }

    /** Request body of POST /web/grade. */
    public record GradeRequest(long questionId, String answer) {
    }

    /** Request body of POST /web/ask. */
    public record AskRequest(String query) {
    }

    @PostMapping("/web/grade")
    @ResponseBody
    public Map<String, Object> grade(@RequestBody GradeRequest request) {
        try {
            GradeResultDto dto = aiClient.grade(request.questionId(), request.answer());
            // Recorded shape carries score+feedback; skipped shape carries only
            // the message. LinkedHashMap tolerates null score/feedback.
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("recorded", dto.recorded());
            if (dto.recorded()) {
                payload.put("score", dto.score());
                payload.put("feedback", dto.feedback());
            } else {
                payload.put("message", dto.message());
            }
            return payload;
        } catch (AiServiceUnavailableException e) {
            return unavailable(e);
        }
    }

    /**
     * Pass-through endpoints return either the DTO (success) or the error
     * map (service down); Object lets the message converter pick by runtime
     * type since the shapes are intentionally different.
     */
    @GetMapping("/web/question")
    @ResponseBody
    public Object question(@RequestParam String topic,
            @RequestParam(defaultValue = "false") boolean wrongOnly,
            @RequestParam(required = false) String excludeIds) {
        try {
            // Convention: the controller ALWAYS passes a non-null excludeIds
            // ("" when the page has no accumulated ids yet) so the service
            // never has to branch on null when expanding the URI template.
            return aiClient.fetchQuestion(topic, wrongOnly, excludeIds == null ? "" : excludeIds);
        } catch (AiServiceUnavailableException e) {
            return unavailable(e);
        }
    }

    @GetMapping("/web/stats")
    @ResponseBody
    public Object stats(@RequestParam String topic) {
        try {
            return aiClient.stats(topic);
        } catch (AiServiceUnavailableException e) {
            return unavailable(e);
        }
    }

    @PostMapping("/web/ask")
    @ResponseBody
    public Object ask(@RequestBody AskRequest request) {
        try {
            return aiClient.ask(request.query());
        } catch (AiServiceUnavailableException e) {
            return unavailable(e);
        }
    }

    /** Common degraded payload: HTTP 200 with the friendly Chinese message. */
    private Map<String, Object> unavailable(AiServiceUnavailableException e) {
        return Map.of("error", e.getMessage());
    }

    /**
     * Caller bugs (null answer/query rejected by AiClientService) surface as
     * HTTP 400, not as the "service down" payload and not as a raw 500.
     */
    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseBody
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String, Object> badRequest(IllegalArgumentException e) {
        return Map.of("error", e.getMessage());
    }
}
