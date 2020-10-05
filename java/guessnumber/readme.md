# Guess a number

In this game, the computer is going to randomly select an integer from 1 to a limit (i.e 100). The player keeps guessing numbers until s/he finds the target number, and the computer will tell each time if the guess was too high or too low.

Java knowledge used in the project:
- loop and nested loops
- if/else statement
- random number generator
- Input/ouput

It also teaches the player how to do binary search

# Game workflow

- Generate a random number in [1, LIMIT]
- Loop until the target number is found or too many guesses:
  - Get the input number
  - Compare the number with target:
    - equal: it is found, compute the score, exit the loop;
    - the number is bigger than the target: show the hint to lower the guess, and wait for the input
    - the number is smaller than the target: show the hint to increase the guess, and waiti for the input.
- If not found, show error message, set the score to -1;
- If found, show success message.
- Return the score

# Discussion

- What loop do we use? why? can we use other loop forms?
- How to get the input? Any issue with the input? How to resolve the issues?
- Can we play multiple times? How can we interact with the computer?
- Can we accumulate the scores?
