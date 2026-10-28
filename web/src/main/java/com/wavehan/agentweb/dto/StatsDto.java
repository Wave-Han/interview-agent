package com.wavehan.agentweb.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Response of GET /api/stats. All three fields are always present in the
 * Python contract (avg_score falls back to 0 when there are no attempts).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record StatsDto(
        Integer attempts,
        @JsonProperty("avg_score") Double avgScore,
        @JsonProperty("wrong_count") Integer wrongCount) {
}
