package prime;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class PrimeTest {
    @Test
    void adds() {
        assertEquals(2, Prime.add(1, 1));
    }
}
