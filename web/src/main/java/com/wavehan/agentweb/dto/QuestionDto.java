package com.wavehan.agentweb.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Response of GET /api/question. Two shapes share this record: the picked
 * question (questionId/topic/difficulty/question set, message null) or the
 * exhausted-pool notice (only message set) — hence nullable wrapper types
 * for the question fields.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
public record QuestionDto(
        @JsonProperty("question_id") Long questionId,
        String topic,
        Integer difficulty,
        String question,
        String message) {
}
