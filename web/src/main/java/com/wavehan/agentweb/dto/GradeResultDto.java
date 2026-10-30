package com.wavehan.agentweb.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Response of POST /api/grade. Success shape: score/feedback recorded=true;
 * failure shape: recorded=false with a message; score/feedback nullable.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GradeResultDto(
        Double score,
        String feedback,
        @JsonProperty("recorded") boolean recorded,
        String message,
        java.util.List<String> reference) {
}
