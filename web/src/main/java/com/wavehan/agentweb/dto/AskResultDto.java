package com.wavehan.agentweb.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Response of POST /api/ask. The recommend id is recovered from the model
 * text on the Python side and may be absent — it maps to null here. The
 * error shape carries only a message.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record AskResultDto(
        String answer,
        @JsonProperty("recommend_question_id") Integer recommendQuestionId,
        String message) {
}
