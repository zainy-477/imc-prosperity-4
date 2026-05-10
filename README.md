
# IMC Prosperity 4 - Rocky Mountain Goats
This writeup shares our strategies for the algorithmic and manual challenges of IMC Prosperity 4 (2026), which brought us to a global rank of 154th out of 22000+ teams - with a total score of 485,221 XIRECs in Phase 1 and 531,123 XIRECs in Phase 2. This was the first attempt at a quantitative trading competition for all of us, and we formed a team through the Discord server created by IMC for this competition. 

> Team Members: Alex Zhang, Annanye Naik, Saksham Arora, Zain Hirji

## Competition Overview

Briefly explain the structure of Prosperity 4.

- 5 rounds
- Algorithmic + manual challenges

<table>
  <tr>
    <th colspan="4" align="center">Qualifying - Phase 1 Results (485,221 XIRECs)</th>
  </tr>
  <tr>
    <th>Round</th>
    <th>Algorithmic</th>
    <th>Manual</th>
    <th>Overall Rank</th>
  </tr>
  <tr>
    <td align="center">1</td>
    <td align="center">105,692</td>
    <td align="center">87,995</td>
    <td align="center">90th</td>
  </tr>
  <tr>
    <td align="center">2</td>
    <td align="center">77,667</td>
    <td align="center">213,867</td>
    <td align="center">277th</td>
  </tr>
</table>


<table>
  <tr>
    <th colspan="4" align="center">Final - Phase 2 Results (531,123 XIRECs)</th>
  </tr>
  <tr>
    <th>Round</th>
    <th>Algorithmic</th>
    <th>Manual</th>
    <th>Overall Rank</th>
  </tr>
  <tr>
    <td align="center">3</td>
    <td align="center">202,131</td>
    <td align="center">70,684</td>
    <td align="center">84th</td>
  </tr>
  <tr>
    <td align="center">4</td>
    <td align="center">149,166</td>
    <td align="center">38,814</td>
    <td align="center">92nd</td>
  </tr>
    <tr>
    <td align="center">5</td>
    <td align="center">-43,997</td>
    <td align="center">114,325</td>
    <td align="center">154th</td>
  </tr>
</table>



## Structural Overview
Contents


# Round 1

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
The first manual challenge of the competition was a trivial optimisation. We were given static orderbooks for two products - **DRYLAND_FLAK** and **EMBER_MUSHROOM** - and had to submit our own buy or sell order for each, at a chosen price and quantity. The exchange would then select a single clearing price that maximised the total traded volume from the orderbook (including the orders that we submitted) and broke ties by choosing the higher price. Our orders would be executed at this clearing price. Finally, we would be able to sell any inventory that we had acquired at fixed prices of 30 XIRECs for **DRYLAND_FLAK** and 20 XIRECs for **EMBER_MUSHROOM**, with a 0.10 XIREC trading fee per unit subtracted from the latter. 

We created Python code to numerically optimise this problem, and submitted the following two orders:
* Buy **DRYLAND_FLAK** at a price of 30 XIRECs and volume of 9999 units.
* Buy **EMBER_MUSHROOM** at a price of 17 XIRECs and volume of 19999 units.

This was one of the optimal solutions and as a result we came joint first in Round 1 of Manual. While this posed a problem that could easily be solved by brute force programming, it is interesting to think about why we obtain the results we do. For example, take a look at the volume of units we chose for our orders - if we were to increase these by 1, the clearing price would have increased by 1 XIREC and our profit would have shrunk by a large margin.

# Round 2

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
Describe:
- our thought process
- the tools we used
- how decisions were made


# Round 3

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
Describe:
- our thought process
- the tools we used
- how decisions were made


# Round 4

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
Describe:
- our thought process
- the tools we used
- how decisions were made


# Round 5

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
Describe:
- our thought process
- the tools we used
- how decisions were made


# Takeaways
