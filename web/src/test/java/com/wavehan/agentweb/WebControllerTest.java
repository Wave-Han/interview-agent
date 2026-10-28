package com.wavehan.agentweb;

import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.wavehan.agentweb.dto.GradeResultDto;
import com.wavehan.agentweb.service.AiClientService;
import com.wavehan.agentweb.service.AiServiceUnavailableException;

/**
 * MockMvc slice for the WebController: page routes and the /web/* JSON
 * endpoints, with AiClientService mocked so no real HTTP to the Python
 * service happens.
 */
@WebMvcTest
class WebControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private AiClientService aiClient;

    @Test
    void gradeDelegates() throws Exception {
        when(aiClient.grade(7L, "a")).thenReturn(new GradeResultDto(0.8, "好", true, null));

        mockMvc.perform(post("/web/grade")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"questionId\":7,\"answer\":\"a\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.recorded").value(true))
                .andExpect(jsonPath("$.score").value(0.8));

        // The controller must forward the raw request values to the service.
        verify(aiClient).grade(7L, "a");
    }

    @Test
    void gradeSkippedSemantics() throws Exception {
        // Mirrors the real Python message when the model skips the grading tool.
        when(aiClient.grade(9L, "skip")).thenReturn(
                new GradeResultDto(null, null, false, "判题未完成(模型未调用判分工具)"));

        mockMvc.perform(post("/web/grade")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"questionId\":9,\"answer\":\"skip\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.recorded").value(false))
                .andExpect(jsonPath("$.message").value(containsString("判题未完成")));
    }

    @Test
    void gradeUnavailableFriendly() throws Exception {
        when(aiClient.grade(anyLong(), anyString()))
                .thenThrow(new AiServiceUnavailableException());

        // Unavailable Python service degrades to HTTP 200 with a friendly error.
        mockMvc.perform(post("/web/grade")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"questionId\":1,\"answer\":\"x\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.error").value(containsString("AI 服务不可用")));
    }

    @Test
    void rootRedirects() throws Exception {
        mockMvc.perform(get("/"))
                .andExpect(status().isFound())
                .andExpect(redirectedUrl("/practice"));
    }
}
