package prime;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class AdderTest {
    @Test
    void adds() {
        assertEquals(2, Adder.add(1, 1));
    }
}
