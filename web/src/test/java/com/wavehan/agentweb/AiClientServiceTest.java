package com.wavehan.agentweb;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.wavehan.agentweb.dto.AskResultDto;
import com.wavehan.agentweb.dto.GradeResultDto;
import com.wavehan.agentweb.dto.QuestionDto;
import com.wavehan.agentweb.dto.StatsDto;
import com.wavehan.agentweb.service.AiClientService;
import com.wavehan.agentweb.service.AiServiceUnavailableException;

/**
 * Unit tests for AiClientService: mocked RestClient fluent chain (no real
 * HTTP) plus plain-Jackson checks of the snake_case DTO contract.
 */
class AiClientServiceTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void gradeReturnsDto() {
        RestClient rest = mock(RestClient.class);
        // RequestBodyUriSpec covers the whole chain (uri/header/body/retrieve).
        RestClient.RequestBodyUriSpec spec = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.ResponseSpec response = mock(RestClient.ResponseSpec.class);
        when(rest.post()).thenReturn(spec);
        when(spec.uri("/api/grade")).thenReturn(spec);
        when(spec.header(anyString(), anyString())).thenReturn(spec);
        // anyMap() pins the body(Object) overload — plain any() would resolve
        // to the more specific body(StreamingHttpOutputMessage.Body) and miss.
        when(spec.body(anyMap())).thenReturn(spec);
        when(spec.retrieve()).thenReturn(response);
        GradeResultDto expected = new GradeResultDto(0.8, "好", true, null);
        when(response.body(GradeResultDto.class)).thenReturn(expected);

        GradeResultDto actual = new AiClientService(rest).grade(7L, "my answer");

        // The service must pass the DTO through untouched.
        assertSame(expected, actual);
        assertEquals(0.8, actual.score(), 1e-9);
        assertEquals("好", actual.feedback());
        assertTrue(actual.recorded());
        assertNull(actual.message());
        // Request body must carry the contract's snake_case keys.
        verify(spec).body(Map.of("question_id", 7L, "answer", "my answer"));
    }

    @Test
    void gradeUnavailableThrowsFriendly() {
        RestClient rest = mock(RestClient.class);
        RestClient.RequestBodyUriSpec spec = mock(RestClient.RequestBodyUriSpec.class);
        when(rest.post()).thenReturn(spec);
        when(spec.uri("/api/grade")).thenReturn(spec);
        when(spec.header(anyString(), anyString())).thenReturn(spec);
        when(spec.body(anyMap())).thenReturn(spec);
        // Service down surfaces as connection refused (RestClientException).
        when(spec.retrieve()).thenThrow(new ResourceAccessException("Connection refused: localhost/127.0.0.1:8000"));

        AiServiceUnavailableException ex = assertThrows(AiServiceUnavailableException.class,
                () -> new AiClientService(rest).grade(7L, "my answer"));

        assertTrue(ex.getMessage().contains("AI 服务不可用"));
        assertNotNull(ex.getCause());
    }

    @Test
    void dtoMapsSnakeCase() throws Exception {
        String json = "{\"question_id\":7,\"topic\":\"jvm\",\"difficulty\":2,"
                + "\"question\":\"谈谈双亲委派\",\"unknown_field\":\"ignored\"}";
        QuestionDto dto = mapper.readValue(json, QuestionDto.class);

        assertEquals(7, dto.questionId());
        assertEquals("jvm", dto.topic());
        assertEquals(2, dto.difficulty());
        assertEquals("谈谈双亲委派", dto.question());
        assertNull(dto.message());
    }

    @Test
    void questionDtoAcceptsMessageVariant() throws Exception {
        // Exhausted-pool shape: only "message" is present.
        QuestionDto dto = mapper.readValue(
                "{\"message\":\"no question available for topic 'jvm'\"}", QuestionDto.class);

        assertNull(dto.questionId());
        assertNull(dto.question());
        assertEquals("no question available for topic 'jvm'", dto.message());
    }

    @Test
    void askResultToleratesMissingRecommendId() throws Exception {
        // The Python side recovers the id from model text; it may be absent.
        AskResultDto withId = mapper.readValue(
                "{\"answer\":\"因为两次握手无法确认双方收发能力\",\"recommend_question_id\":9}",
                AskResultDto.class);
        assertEquals(9, withId.recommendQuestionId());
        assertEquals("因为两次握手无法确认双方收发能力", withId.answer());

        AskResultDto withoutId = mapper.readValue(
                "{\"answer\":\"因为两次握手无法确认双方收发能力\"}", AskResultDto.class);
        assertNull(withoutId.recommendQuestionId());
    }

    @Test
    void nullArgumentsFailFastAsIllegalArgument() {
        RestClient rest = mock(RestClient.class);
        AiClientService service = new AiClientService(rest);

        // A null answer/query is a caller bug: it must surface as
        // IllegalArgumentException, never be mistranslated to "service down".
        assertThrows(IllegalArgumentException.class, () -> service.grade(7L, null));
        assertThrows(IllegalArgumentException.class, () -> service.ask(null));
    }

    @Test
    void statsMapsSnakeCase() throws Exception {
        StatsDto dto = mapper.readValue(
                "{\"attempts\":3,\"avg_score\":0.67,\"wrong_count\":1}", StatsDto.class);

        assertEquals(3, dto.attempts());
        assertEquals(0.67, dto.avgScore(), 1e-9);
        assertEquals(1, dto.wrongCount());
    }
}
